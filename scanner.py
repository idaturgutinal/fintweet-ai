#!/usr/bin/env python3
"""
FinTweet AI - Kaynak Tarama Scripti (scanner.py)
Brave Search ve X API ile kaynaklari tarar, bulgulari JSON olarak kaydeder.
OpenClaw botu bu bulgulari okuyup icerik uretir.

Kullanim:
  python3 scanner.py                    # Tum kaynaklari tara
  python3 scanner.py --category breaking_news  # Belirli kategori
  python3 scanner.py --web-only         # Sadece web tarama
  python3 scanner.py --twitter-only     # Sadece twitter tarama
  python3 scanner.py --slot sabah_brifing  # Zamanlanmis slot icin
"""

from error_notifier import send_error_alert
import os
import sys
import json
import time
import hashlib
import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Ayarlar ---
WORKSPACE = Path.home() / ".openclaw" / "workspace"
SOURCES_FILE = WORKSPACE / "sources.json"
DB_FILE = WORKSPACE / "fintweet.db"
FINDINGS_DIR = WORKSPACE / "findings"
FINDINGS_DIR.mkdir(exist_ok=True)

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
TWITTER_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


def load_sources():
    """Kaynak konfigurasyonunu yukle."""
    with open(SOURCES_FILE, "r") as f:
        return json.load(f)


def init_db():
    """SQLite veritabanini olustur."""
    conn = sqlite3.connect(str(DB_FILE))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT UNIQUE,
            text TEXT NOT NULL,
            content_type TEXT,
            source_category TEXT,
            tone TEXT DEFAULT 'neutral',
            length_type TEXT DEFAULT 'medium',
            slot TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            posted_at TIMESTAMP,
            status TEXT DEFAULT 'draft'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS engagement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            retweets INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            bookmarks INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            profile_clicks INTEGER DEFAULT 0,
            score REAL DEFAULT 0,
            measured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tweet_id) REFERENCES tweets(tweet_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            source_type TEXT DEFAULT 'twitter',
            total_tweets INTEGER DEFAULT 0,
            avg_score REAL DEFAULT 0,
            last_scanned TIMESTAMP,
            UNIQUE(name, category)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT UNIQUE,
            source_type TEXT NOT NULL,
            source_category TEXT NOT NULL,
            source_name TEXT,
            title TEXT,
            snippet TEXT,
            url TEXT,
            raw_data TEXT,
            relevance_score REAL DEFAULT 0,
            processed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_type TEXT NOT NULL,
            category TEXT,
            findings_count INTEGER DEFAULT 0,
            error TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)

    conn.commit()
    return conn


def brave_search(query, max_results=5):
    """Brave Search API ile web araması yap."""
    import requests

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        print("[HATA] BRAVE_SEARCH_API_KEY bulunamadi!")
        return []

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }

    params = {
        "q": query,
        "count": max_results,
        "freshness": "pd",  # Son 24 saat
    }

    try:
        resp = requests.get(BRAVE_API_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("description", ""),
                "url": item.get("url", ""),
                "age": item.get("age", ""),
                "source": item.get("meta_url", {}).get("hostname", ""),
            })
        return results

    except Exception as e:
        print(f"[HATA] Brave Search hatasi ({query}): {e}")
        return []


def twitter_search(query, max_results=10):
    """X API v2 ile tweet araması yap (Bearer Token)."""
    import requests

    bearer = os.environ.get("TWITTER_BEARER_TOKEN")
    if not bearer:
        print("[HATA] TWITTER_BEARER_TOKEN bulunamadi!")
        return []

    headers = {"Authorization": f"Bearer {bearer}"}

    params = {
        "query": query,
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,author_id,lang",
        "sort_order": "relevancy",
    }

    try:
        resp = requests.get(TWITTER_SEARCH_URL, headers=headers, params=params, timeout=15)

        if resp.status_code == 429:
            print("[UYARI] X API rate limit - bekleniyor...")
            time.sleep(15)
            return []

        if resp.status_code != 200:
            print(f"[HATA] X API hatasi: {resp.status_code} - {resp.text[:200]}")
            return []

        data = resp.json()
        results = []
        for tweet in data.get("data", []):
            metrics = tweet.get("public_metrics", {})
            results.append({
                "tweet_id": tweet.get("id"),
                "text": tweet.get("text", ""),
                "created_at": tweet.get("created_at", ""),
                "author_id": tweet.get("author_id", ""),
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "replies": metrics.get("reply_count", 0),
                "impressions": metrics.get("impression_count", 0),
            })
        return results

    except Exception as e:
        print(f"[HATA] Twitter Search hatasi ({query}): {e}")
        return []


def compute_hash(text):
    """Icerik hash'i olustur (tekrar onleme)."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def parse_age_to_hours(age_str):
    """'6 hours ago' -> 6.0, '1 day ago' -> 24.0, '34 minutes ago' -> 0.57"""
    import re as _re
    age_str = age_str.lower()
    match = _re.search(r'(\d+)', age_str)
    if not match:
        return None
    num = int(match.group(1))
    if "minute" in age_str:
        return num / 60
    elif "hour" in age_str:
        return float(num)
    elif "day" in age_str:
        return num * 24.0
    elif "week" in age_str:
        return num * 168.0
    return None


CRYPTO_CATEGORIES = {"breaking_news", "whale_alerts", "macro_economy", "crypto_analysis",
                     "turkey_crypto", "turkey_finance", "regulation_web", "etf_flows",
                     "etf_tracking", "stablecoin_flows", "onchain", "ai_crypto",
                     "data_platforms", "news_sites", "macro_data",
                     "turkey_news_web"}  # _web sonekliler de kripto/finans


def calculate_web_score(item, cat_key):
    """Brave Search sonucu icin relevance_score hesapla."""
    score = 50 if cat_key in CRYPTO_CATEGORIES else 30

    age_str = item.get("age", "")
    if age_str:
        age_hours = parse_age_to_hours(age_str)
        if age_hours is not None:
            if age_hours < 1:
                score += 70
            elif age_hours < 6:
                score += 50
            elif age_hours < 12:
                score += 30
            elif age_hours < 24:
                score += 10

    return score


def scan_web_sources(conn, sources_config, category=None):
    """Web kaynaklarini tara."""
    web_sources = sources_config.get("web_sources", {})
    total_findings = 0

    for cat_key, cat_data in web_sources.items():
        if category and cat_key != category:
            continue

        # Interval kontrolu
        last_scan = conn.execute(
            "SELECT completed_at FROM scan_log WHERE category=? AND scan_type='web' AND completed_at IS NOT NULL ORDER BY id DESC LIMIT 1",
            (cat_key,)
        ).fetchone()
        if last_scan and last_scan[0]:
            try:
                last_time = datetime.fromisoformat(last_scan[0])
                interval = cat_data.get("scan_interval_minutes", 180)
                elapsed = (datetime.now() - last_time).total_seconds() / 60
                if elapsed < interval:
                    print(f"  [SKIP] {cat_key}: son tarama {int(elapsed)}dk once, interval {interval}dk")
                    continue
            except (ValueError, TypeError):
                pass

        print(f"\n[WEB] {cat_data['label']} taranıyor...")
        log_id = log_scan_start(conn, "web", cat_key)

        cat_findings = 0
        for query in cat_data.get("queries", []):
            results = brave_search(query)

            for item in results:
                content = f"{item['title']} {item['snippet']}"
                h = compute_hash(content)
                web_score = calculate_web_score(item, cat_key)

                try:
                    before = conn.total_changes
                    conn.execute("""
                        INSERT OR IGNORE INTO findings
                        (hash, source_type, source_category, source_name, title, snippet, url, raw_data, relevance_score)
                        VALUES (?, 'web', ?, ?, ?, ?, ?, ?, ?)
                    """, (h, cat_key, item.get("source", ""), item["title"],
                          item["snippet"], item["url"], json.dumps(item), web_score))
                    if conn.total_changes > before:
                        cat_findings += 1
                except sqlite3.IntegrityError:
                    pass  # Zaten var, atla

            time.sleep(0.5)  # Rate limit koruması

        conn.commit()
        log_scan_end(conn, log_id, cat_findings)
        total_findings += cat_findings
        print(f"  -> {cat_findings} yeni bulgu")

    return total_findings


def scan_twitter_sources(conn, sources_config, category=None):
    """Twitter kaynaklarini tara."""
    twitter_sources = sources_config.get("twitter_sources", {})
    total_findings = 0

    for cat_key, cat_data in twitter_sources.items():
        if category and cat_key != category:
            continue

        # Interval kontrolu
        interval_hours = cat_data.get("scan_interval_hours", 4)
        interval = interval_hours * 60
        last_scan = conn.execute(
            "SELECT completed_at FROM scan_log WHERE category=? AND scan_type='twitter' AND completed_at IS NOT NULL ORDER BY id DESC LIMIT 1",
            (cat_key,)
        ).fetchone()
        if last_scan and last_scan[0]:
            try:
                last_time = datetime.fromisoformat(last_scan[0])
                elapsed = (datetime.now() - last_time).total_seconds() / 60
                if elapsed < interval:
                    print(f"  [SKIP] {cat_key}: son tarama {int(elapsed)}dk once, interval {interval}dk")
                    continue
            except (ValueError, TypeError):
                pass

        print(f"\n[TWITTER] {cat_data['label']} taranıyor...")
        log_id = log_scan_start(conn, "twitter", cat_key)

        accounts = cat_data.get("accounts", [])
        cat_findings = 0

        # 5'li batch'ler halinde tara
        for batch_i in range(0, max(len(accounts), 1), 5):
            batch = accounts[batch_i:batch_i+5]
            query = " OR ".join(f"from:{acc.lstrip('@')}" for acc in batch)

            if not query:
                continue

            results = twitter_search(query)

            for tweet in results:
                h = compute_hash(tweet["text"])
                try:
                    before = conn.total_changes
                    conn.execute("""
                        INSERT OR IGNORE INTO findings
                        (hash, source_type, source_category, source_name, title, snippet, url, raw_data, relevance_score)
                        VALUES (?, 'twitter', ?, ?, ?, ?, ?, ?, ?)
                    """, (h, cat_key, tweet.get("author_id", ""),
                          tweet["text"][:100], tweet["text"],
                          f"https://x.com/i/status/{tweet['tweet_id']}",
                          json.dumps(tweet),
                          tweet.get("likes", 0) + tweet.get("retweets", 0) * 2))
                    if conn.total_changes > before:
                        cat_findings += 1
                except sqlite3.IntegrityError:
                    pass

            time.sleep(1)  # Rate limit

        conn.commit()
        log_scan_end(conn, log_id, cat_findings)
        total_findings += cat_findings
        print(f"  -> {cat_findings} yeni bulgu")

    return total_findings


def log_scan_start(conn, scan_type, category):
    """Tarama logu baslat."""
    c = conn.execute("""
        INSERT INTO scan_log (scan_type, category) VALUES (?, ?)
    """, (scan_type, category))
    conn.commit()
    return c.lastrowid


def log_scan_end(conn, log_id, findings_count, error=None):
    """Tarama logu tamamla."""
    conn.execute("""
        UPDATE scan_log SET findings_count=?, error=?, completed_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (findings_count, error, log_id))
    conn.commit()


def get_unprocessed_findings(conn, limit=10):
    """Islenmemis bulgulari getir (oncelige gore sirali)."""
    cursor = conn.execute("""
        SELECT id, source_type, source_category, title, snippet, url, raw_data, relevance_score
        FROM findings
        WHERE processed = 0
        ORDER BY
            CASE source_category
                WHEN 'breaking_news' THEN 1
                WHEN 'regulation' THEN 2
                WHEN 'onchain' THEN 3
                ELSE 5
            END,
            relevance_score DESC,
            created_at DESC
        LIMIT ?
    """, (limit,))
    return cursor.fetchall()


def export_findings_for_bot(conn, slot=None):
    """Islenmemis bulgulari bot icin JSON dosyasina aktar."""
    findings = get_unprocessed_findings(conn, limit=15)

    if not findings:
        print("[BILGI] Yeni bulgu yok.")
        return None

    export = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "slot": slot,
        "findings_count": len(findings),
        "findings": [],
    }

    for f in findings:
        fid, src_type, src_cat, title, snippet, url, raw_data, score = f
        export["findings"].append({
            "id": fid,
            "source_type": src_type,
            "source_category": src_cat,
            "title": title,
            "snippet": snippet,
            "url": url,
            "relevance_score": score,
        })

    # JSON dosyasina yaz
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"findings_{timestamp}.json"
    filepath = FINDINGS_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    # Ayrica latest.json olarak da kaydet (bot bunu okur)
    latest_path = FINDINGS_DIR / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print(f"[OK] {len(findings)} bulgu kaydedildi: {filepath}")
    return filepath


def mark_as_processed(conn, finding_ids):
    """Bulgulari islenmis olarak isaretle."""
    for fid in finding_ids:
        conn.execute("UPDATE findings SET processed = 1 WHERE id = ?", (fid,))
    conn.commit()


def print_summary(conn):
    """Tarama ozeti yazdir."""
    cursor = conn.execute("""
        SELECT source_type, source_category, COUNT(*), SUM(CASE WHEN processed=0 THEN 1 ELSE 0 END)
        FROM findings
        GROUP BY source_type, source_category
        ORDER BY source_type, source_category
    """)

    print("\n" + "=" * 60)
    print("TARAMA OZETI")
    print("=" * 60)
    print(f"{'Tip':<10} {'Kategori':<25} {'Toplam':>8} {'Yeni':>8}")
    print("-" * 60)
    for row in cursor.fetchall():
        print(f"{row[0]:<10} {row[1]:<25} {row[2]:>8} {row[3]:>8}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="FinTweet AI Kaynak Tarayici")
    parser.add_argument("--category", help="Belirli bir kategori tara")
    parser.add_argument("--web-only", action="store_true", help="Sadece web kaynaklari")
    parser.add_argument("--twitter-only", action="store_true", help="Sadece Twitter kaynaklari")
    parser.add_argument("--slot", help="Zamanlanmis slot adi (sabah_brifing, piyasa_acilis vs.)")
    parser.add_argument("--export", action="store_true", help="Bulgulari bot icin JSON'a aktar")
    parser.add_argument("--summary", action="store_true", help="Tarama ozetini goster")
    args = parser.parse_args()

    # Kaynaklari yukle
    if not SOURCES_FILE.exists():
        print(f"[HATA] Kaynak dosyasi bulunamadi: {SOURCES_FILE}")
        sys.exit(1)

    sources = load_sources()
    conn = init_db()

    print(f"[BASLA] FinTweet Scanner - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    total = 0

    if not args.twitter_only:
        total += scan_web_sources(conn, sources, args.category)

    if not args.web_only:
        total += scan_twitter_sources(conn, sources, args.category)

    print(f"\n[SONUC] Toplam {total} yeni bulgu")

    if args.export or args.slot:
        export_findings_for_bot(conn, slot=args.slot)

    if args.summary:
        print_summary(conn)

    conn.close()
    print("[BITTI]")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_error_alert("scanner", str(e))
        raise
