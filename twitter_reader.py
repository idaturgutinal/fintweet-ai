#!/usr/bin/env python3
"""
FinTweet AI - Twitter Hesap Okuyucu
Belirtilen hesapların son tweetlerini Twitter API v2 ile çeker.

Kullanim:
  python3 twitter_reader.py                        # Tüm kaynaklari tara
  python3 twitter_reader.py --accounts @whale_alert @WatcherGuru
  python3 twitter_reader.py --category breaking_news
  python3 twitter_reader.py --search "bitcoin ETF"
  python3 twitter_reader.py --cost                  # API maliyet tahmini

Twitter API v2 Basic plan: $200/ay, 10,000 tweet okuma/ay
Pay-per-use hesaplama yaparak limiti asmamak icin kontrol saglar.

Gereksinim: TWITTER_BEARER_TOKEN env variable
"""

import os
import sys
import json
import sqlite3
import argparse
import requests
from datetime import datetime, timedelta, timezone

# ============================================================
# CONFIG
# ============================================================

DB_PATH = os.path.expanduser("~/.openclaw/workspace/fintweet.db")
SOURCES_PATH = os.path.expanduser("~/.openclaw/workspace/sources.json")
FINDINGS_DIR = os.path.expanduser("~/.openclaw/workspace/findings")
import urllib.parse
BEARER_TOKEN = urllib.parse.unquote(os.environ.get("TWITTER_BEARER_TOKEN", ""))

# Maliyet kontrolu
MONTHLY_TWEET_READ_LIMIT = 10000  # Basic plan
COST_PER_TWEET_READ = 0.02        # Yaklaşık $200 / 10000

HEADERS = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "User-Agent": "FinTweetAI/1.0"
}

def init_db():
    """Twitter okuma tablolarini olustur."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # API kullanim takibi
    c.execute("""CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT,
        tweet_count INTEGER,
        timestamp TEXT
    )""")
    
    # Okunan tweetler (cache)
    c.execute("""CREATE TABLE IF NOT EXISTS twitter_cache (
        tweet_id TEXT PRIMARY KEY,
        author_username TEXT,
        author_name TEXT,
        text TEXT,
        created_at TEXT,
        like_count INTEGER DEFAULT 0,
        retweet_count INTEGER DEFAULT 0,
        reply_count INTEGER DEFAULT 0,
        category TEXT,
        fetched_at TEXT
    )""")
    
    conn.commit()
    return conn

def get_monthly_usage(conn):
    """Bu ayki API kullanimini hesapla."""
    c = conn.cursor()
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0).isoformat()
    c.execute("SELECT COALESCE(SUM(tweet_count), 0) FROM api_usage WHERE timestamp > ?", (month_start,))
    return c.fetchone()[0]

def log_usage(conn, endpoint, count):
    """API kullanimini kaydet."""
    c = conn.cursor()
    c.execute("INSERT INTO api_usage (endpoint, tweet_count, timestamp) VALUES (?, ?, ?)",
              (endpoint, count, datetime.now(timezone.utc).isoformat()))
    conn.commit()

def get_user_id(username):
    """Username'den user ID al."""
    clean = username.lstrip('@')
    url = f"https://api.x.com/2/users/by/username/{clean}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    
    if resp.status_code == 200:
        data = resp.json().get('data', {})
        return data.get('id'), data.get('name', clean)
    elif resp.status_code == 429:
        print(f"  Rate limit! Bekle ve tekrar dene.")
        return None, None
    else:
        print(f"  Kullanici bulunamadi: @{clean} ({resp.status_code})")
        return None, None

def get_user_tweets(user_id, username, max_results=5, since_hours=24):
    """Kullanicinin son tweetlerini cek."""
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = {
        "max_results": min(max(max_results, 5), 100),
        "tweet.fields": "created_at,public_metrics,referenced_tweets"
    }

    resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
    
    if resp.status_code == 200:
        data = resp.json()
        tweets = data.get('data', [])
        return tweets
    elif resp.status_code == 429:
        print(f"  Rate limit @{username}! Atlanıyor...")
        return []
    else:
        print(f"  Tweet cekme hatasi @{username}: {resp.status_code}")
        return []

def search_recent_tweets(query, max_results=10):
    """Son tweetlerde arama yap."""
    url = "https://api.x.com/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": min(max(max_results, 10), 100),
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username,name",
    }
    
    resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
    
    if resp.status_code == 200:
        data = resp.json()
        tweets = data.get('data', [])
        users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
        
        # Kullanici bilgisini tweete ekle
        for t in tweets:
            author = users.get(t.get('author_id'), {})
            t['author_username'] = author.get('username', 'unknown')
            t['author_name'] = author.get('name', 'Unknown')
        
        return tweets
    elif resp.status_code == 429:
        print(f"  Search rate limit! Bekle...")
        return []
    else:
        print(f"  Arama hatasi: {resp.status_code} {resp.text[:100]}")
        return []

def cache_tweets(conn, tweets, username, category=""):
    """Tweetleri cache'e kaydet."""
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    
    for t in tweets:
        metrics = t.get('public_metrics', {})
        c.execute("""INSERT OR REPLACE INTO twitter_cache 
            (tweet_id, author_username, author_name, text, created_at, 
             like_count, retweet_count, reply_count, category, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (t['id'], 
             t.get('author_username', username),
             t.get('author_name', username),
             t['text'],
             t.get('created_at', now),
             metrics.get('like_count', 0),
             metrics.get('retweet_count', 0),
             metrics.get('reply_count', 0),
             category,
             now))
    
    conn.commit()

def save_as_findings(tweets, username, category):
    """Findings formatında kaydet (bot'un okuyabilmesi icin)."""
    os.makedirs(FINDINGS_DIR, exist_ok=True)
    
    findings = []
    for t in tweets:
        metrics = t.get('public_metrics', {})
        findings.append({
            "source": f"twitter/@{username}",
            "source_category": category,
            "title": t['text'][:100],
            "snippet": t['text'],
            "url": f"https://x.com/{username}/status/{t['id']}",
            "tweet_id": t['id'],
            "engagement": {
                "likes": metrics.get('like_count', 0),
                "retweets": metrics.get('retweet_count', 0),
                "replies": metrics.get('reply_count', 0),
            },
            "timestamp": t.get('created_at', ''),
            "quotable": True,  # Bu tweet alinti yapilabilir
        })
    
    return findings

def scan_twitter_sources(categories=None, max_per_account=5):
    """sources.json'daki Twitter hesaplarini tara."""
    if not BEARER_TOKEN:
        print("HATA: TWITTER_BEARER_TOKEN bulunamadi!")
        return []
    
    conn = init_db()
    
    # Maliyet kontrolu
    monthly_usage = get_monthly_usage(conn)
    print(f"Bu ay API kullanimi: {monthly_usage}/{MONTHLY_TWEET_READ_LIMIT} tweet")
    
    if monthly_usage >= MONTHLY_TWEET_READ_LIMIT * 0.9:
        print("UYARI: Aylik limitin %90'ina ulasildi! Tarama kisitlaniyor.")
        max_per_account = 3
    
    if monthly_usage >= MONTHLY_TWEET_READ_LIMIT:
        print("HATA: Aylik limit asildi! Tarama durduruluyor.")
        conn.close()
        return []
    
    # Kaynaklari yukle
    if not os.path.exists(SOURCES_PATH):
        print(f"HATA: {SOURCES_PATH} bulunamadi!")
        conn.close()
        return []
    
    with open(SOURCES_PATH, 'r') as f:
        sources = json.load(f)
    
    twitter_sources = sources.get('twitter_sources', {})
    all_findings = []
    total_tweets_read = 0
    
    for cat_key, cat_data in twitter_sources.items():
        if categories and cat_key not in categories:
            continue
        
        label = cat_data.get('label', cat_key)
        accounts = cat_data.get('accounts', [])
        priority = cat_data.get('priority', 'medium')
        
        print(f"\n[{label}] ({priority}) - {len(accounts)} hesap")
        
        for account in accounts:
            clean = account.lstrip('@')
            
            # Limit kontrolu
            if total_tweets_read + max_per_account > MONTHLY_TWEET_READ_LIMIT - monthly_usage:
                print(f"  Limit yaklasiyor, tarama durduruluyor.")
                break
            
            # User ID al
            user_id, name = get_user_id(clean)
            if not user_id:
                continue
            
            total_tweets_read += 1  # user lookup da sayilir
            
            # Tweetleri cek
            tweets = get_user_tweets(user_id, clean, max_results=max_per_account)
            total_tweets_read += len(tweets)
            
            if tweets:
                # Cache'e kaydet
                cache_tweets(conn, tweets, clean, cat_key)
                
                # Findings olarak kaydet
                findings = save_as_findings(tweets, clean, cat_key)
                all_findings.extend(findings)
                
                print(f"  @{clean}: {len(tweets)} tweet")
                for t in tweets[:2]:  # Ilk 2'yi goster
                    print(f"    -> {t['text'][:80]}...")
            else:
                print(f"  @{clean}: yeni tweet yok")
    
    # Kullanimi kaydet
    log_usage(conn, "scan_twitter_sources", total_tweets_read)
    
    # Findings dosyasina kaydet
    if all_findings:
        findings_path = os.path.join(FINDINGS_DIR, f"twitter_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json")
        with open(findings_path, 'w', encoding='utf-8') as f:
            json.dump(all_findings, f, ensure_ascii=False, indent=2)
        
        # latest.json'u guncelle (mevcut findings ile birlestir)
        latest_path = os.path.join(FINDINGS_DIR, "latest.json")
        existing = []
        if os.path.exists(latest_path):
            try:
                with open(latest_path, 'r') as f:
                    existing = json.load(f)
            except:
                pass
        
        # Twitter findings'i ekle
        combined = existing + all_findings
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        
        print(f"\nToplam: {len(all_findings)} bulgu kaydedildi")
        print(f"API kullanimi: +{total_tweets_read} tweet (toplam: {monthly_usage + total_tweets_read})")
    
    conn.close()
    return all_findings

def show_cost_estimate():
    """Maliyet tahmini goster."""
    conn = init_db()
    monthly_usage = get_monthly_usage(conn)
    
    print("=" * 50)
    print("  TWITTER API MALIYET TAHMINI")
    print("=" * 50)
    print(f"\n  Bu ay okunan tweet: {monthly_usage}")
    print(f"  Aylik limit: {MONTHLY_TWEET_READ_LIMIT}")
    print(f"  Kalan: {MONTHLY_TWEET_READ_LIMIT - monthly_usage}")
    print(f"  Tahmini maliyet: ~${monthly_usage * COST_PER_TWEET_READ:.2f}")
    print(f"\n  Gunluk ortalama: ~{monthly_usage // max(datetime.now(timezone.utc).day, 1)} tweet/gun")
    print(f"  Ay sonuna kadar: ~{(MONTHLY_TWEET_READ_LIMIT - monthly_usage) // max(30 - datetime.now(timezone.utc).day, 1)} tweet/gun kaldi")
    print("=" * 50)
    
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="FinTweet AI Twitter Okuyucu")
    parser.add_argument("--accounts", nargs='+', help="Belirli hesaplari tara")
    parser.add_argument("--category", help="Belirli kategoriyi tara (breaking_news, macro_economy, vs)")
    parser.add_argument("--search", help="Tweet ara")
    parser.add_argument("--max", type=int, default=5, help="Hesap basi max tweet (default: 5)")
    parser.add_argument("--cost", action="store_true", help="Maliyet tahmini")
    parser.add_argument("--all", action="store_true", help="Tum kaynaklari tara")
    
    args = parser.parse_args()
    
    if not BEARER_TOKEN:
        print("HATA: TWITTER_BEARER_TOKEN bulunamadi!")
        print("  source ~/.fintweet-env")
        sys.exit(1)
    
    if args.cost:
        show_cost_estimate()
    elif args.search:
        conn = init_db()
        tweets = search_recent_tweets(args.search, max_results=args.max)
        if tweets:
            log_usage(conn, "search", len(tweets))
            print(f"\n'{args.search}' icin {len(tweets)} sonuc:\n")
            for t in tweets:
                metrics = t.get('public_metrics', {})
                print(f"  @{t.get('author_username', '?')}: {t['text'][:120]}")
                print(f"    ❤️ {metrics.get('like_count',0)} | 🔁 {metrics.get('retweet_count',0)} | 💬 {metrics.get('reply_count',0)}")
                print(f"    🔗 https://x.com/{t.get('author_username','')}/status/{t['id']}")
                print()
        conn.close()
    elif args.accounts:
        conn = init_db()
        total = 0
        for acc in args.accounts:
            clean = acc.lstrip('@')
            user_id, name = get_user_id(clean)
            if user_id:
                tweets = get_user_tweets(user_id, clean, max_results=args.max)
                if tweets:
                    cache_tweets(conn, tweets, clean, "manual")
                    total += len(tweets)
                    print(f"\n@{clean} ({name}) - {len(tweets)} tweet:")
                    for t in tweets:
                        metrics = t.get('public_metrics', {})
                        print(f"  {t['text'][:120]}")
                        print(f"  ❤️ {metrics.get('like_count',0)} | 🔗 https://x.com/{clean}/status/{t['id']}")
                        print()
        log_usage(conn, "manual_accounts", total)
        conn.close()
    elif args.category:
        scan_twitter_sources(categories=[args.category], max_per_account=args.max)
    elif args.all:
        scan_twitter_sources(max_per_account=args.max)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
