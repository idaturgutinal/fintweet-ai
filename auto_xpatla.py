#!/usr/bin/env python3
"""
FinTweet AI - Otomatik XPatla Tweet Onerisi (auto_xpatla.py)
=============================================================
Scanner bulgularini okur, onemli olanlar icin XPatla'dan tweet onerisi uretir,
Telegram'a gonderir. Sabah slotunda XPatla bagimsiz kesif de yapar.

Gunde 4 kez calisir (07:35, 12:05, 17:05, 21:35 TR).
7/24 aktif (kripto piyasasi durmuyor).

Kullanim:
  python3 auto_xpatla.py              # Normal calisma (son 1.5 saat bulgulari)
  python3 auto_xpatla.py --dry-run    # Test modu (API cagirmaz)
  python3 auto_xpatla.py --force      # Kredi limitini gormezden gel
"""

from error_notifier import send_error_alert
from tweet_validator import validate_tweet
import os
import sys
import re
import json
import sqlite3
import hashlib
import argparse
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- Ortam degiskenlerini yukle ---
ENV_FILE = os.path.expanduser("~/.fintweet-env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

# --- Sabitler ---
WORKSPACE = Path.home() / ".openclaw" / "workspace"
DB_PATH = WORKSPACE / "fintweet.db"
XPATLA_BASE_URL = "https://xpatla.com/api/v1"
XPATLA_API_KEY = os.environ.get("XPATLA_API_KEY", "")
TWITTER_USERNAME = "equinoxistr"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Gunluk XPatla cagrisi limiti (kredi tasarrufu)
DAILY_MAX_CALLS = 8

# Otomatik onay - yuksek skorlu tweetler direkt atilir
AUTO_APPROVE_ENABLED = True
AUTO_APPROVE_SCORE = 75

# Anti-bot cooldown: auto-approve arasi minimum bekleme suresi
COOLDOWN_FILE = "/tmp/fintweet_last_auto.txt"
COOLDOWN_MIN_MINUTES = 45
COOLDOWN_MAX_MINUTES = 90


# Slot-kategori eslesmesi: her saat dilimine uygun icerik
SLOT_CATEGORY_MAP = {
    "morning_macro": ["macro_economy", "breaking_news", "turkey_economy"],
    "crypto_analysis": ["crypto_analysis", "etf_flows", "etf_tracking"],
    "breaking_onchain": ["breaking_news", "onchain", "whale_alerts"],
    "turkey_regulation": ["turkey_finance", "turkey_crypto", "regulation_web"],
    "defi_altcoin": ["defi_altcoins", "stablecoin_flows", "social_signals"],
    "us_market_open": ["macro_economy", "etf_tracking", "breaking_news"],
    "whale_social": ["whale_alerts", "social_signals", "onchain"],
    "night_global": ["geopolitics", "ai_crypto", "ai_developments", "science_space"],
}
  # Pro tier: 1500 kredi/ay, gunde ~8 cagri makul
# Minimum onem skoru (bunun altindaki bulgular icin tweet uretme)
MIN_RELEVANCE_SCORE = 0
# Son kac saat icindeki bulgulari isle
LOOKBACK_HOURS = 1.5
# Her bulgu icin uretilecek tweet sayisi
TWEETS_PER_FINDING = 1
# Varsayilan config
DEFAULT_CONFIG = {"format": "punch", "persona": "authority", "tone": "default"}

# Kategori -> format/persona/tone eslesmesi
CATEGORY_CONFIG = {
    # === Kripto / Finans (ana icerik %70-80) ===
    "breaking_news": {"format": "punch", "persona": "news", "tone": "raw"},
    "whale_alerts": {"format": "spark", "persona": "mentalist", "tone": "deadpan"},
    "macro_economy": {"format": "spark", "persona": "authority", "tone": "polished"},
    "crypto_analysis": {"format": "punch", "persona": "authority", "tone": "default"},
    "turkey_crypto": {"format": "punch", "persona": "bilgi", "tone": "default"},
    "turkey_finance": {"format": "spark", "persona": "authority", "tone": "polished"},
    "influential": {"format": "punch", "persona": "sigma", "tone": "raw"},
    "news_sites": {"format": "punch", "persona": "news", "tone": "raw"},
    "data_platforms": {"format": "spark", "persona": "authority", "tone": "default"},
    "onchain": {"format": "spark", "persona": "mentalist", "tone": "deadpan"},
    "social_signals": {"format": "punch", "persona": "shitpost", "tone": "unhinged"},
    "regulation_web": {"format": "spark", "persona": "authority", "tone": "polished"},
    "etf_flows": {"format": "spark", "persona": "authority", "tone": "polished"},
    "ai_crypto": {"format": "punch", "persona": "news", "tone": "default"},
    "stablecoin_flows": {"format": "spark", "persona": "mentalist", "tone": "deadpan"},
    "etf_tracking": {"format": "spark", "persona": "authority", "tone": "polished"},
    # === Yan icerik (%20-30) ===
    "tech_news": {"format": "spark", "persona": "authority", "tone": "polished"},
    "ai_developments": {"format": "spark", "persona": "bilgi", "tone": "polished"},
    "geopolitics": {"format": "punch", "persona": "news", "tone": "raw"},
    "geopolitics_web": {"format": "punch", "persona": "news", "tone": "raw"},
    "turkey_economy": {"format": "punch", "persona": "news", "tone": "polished"},
    "turkey_news_web": {"format": "punch", "persona": "news", "tone": "polished"},
    "world_leaders_policy": {"format": "spark", "persona": "authority", "tone": "polished"},
    "world_news": {"format": "punch", "persona": "news", "tone": "raw"},
    "energy_commodities": {"format": "spark", "persona": "authority", "tone": "default"},
    "energy_commodities_web": {"format": "spark", "persona": "authority", "tone": "default"},
    "science_space": {"format": "spark", "persona": "bilgi", "tone": "polished"},
    "science_space_web": {"format": "spark", "persona": "bilgi", "tone": "polished"},
    "startup_vc": {"format": "spark", "persona": "hustler", "tone": "raw"},
    "startup_vc_web": {"format": "spark", "persona": "hustler", "tone": "raw"},
}

# Ingilizce kaynak kategorileri (bu kategorilerdeki bulgular icin language="english")
ENGLISH_CATEGORIES = {"influential", "crypto_analysis", "ai_developments", "startup_vc", "startup_vc_web"}

# Kategori oncelik siralama (dusuk sayi = yuksek oncelik)
# Kripto/finans (1-11) her zaman yan icerikten (12-18) once gelir
CATEGORY_PRIORITY = {
    # === Kripto / Finans (ana) ===
    "breaking_news": 1,
    "price_alert": 2,
    "whale_alerts": 3,
    "regulation": 4,
    "regulation_web": 4,
    "etf_flows": 4,
    "stablecoin_flows": 5,
    "onchain": 5,
    "macro_economy": 6,
    "macro_data": 6,
    "etf_tracking": 6,
    "crypto_analysis": 7,
    "turkey_crypto": 8,
    "turkey_finance": 8,
    "influential": 9,
    "ai_crypto": 9,
    "news_sites": 10,
    "data_platforms": 10,
    "social_signals": 11,
    # === Yan icerik ===
    "turkey_economy": 12,
    "turkey_news_web": 12,
    "geopolitics": 13,
    "geopolitics_web": 13,
    "world_leaders_policy": 13,
    "energy_commodities": 14,
    "energy_commodities_web": 14,
    "tech_news": 15,
    "ai_developments": 15,
    "science_space": 16,
    "science_space_web": 16,
    "startup_vc": 17,
    "startup_vc_web": 17,
    "world_news": 18,
}

# XPatla bagimsiz kesif konulari (saate gore, UTC)
# Sabah (UTC 4) = makro/genel, Aksam (UTC 18) = on-chain/whale/DeFi
DISCOVERY_TOPICS = {
    4: "bitcoin kripto piyasa makro ekonomi son gelismeler dunya gundemi teknoloji Turkiye ekonomi",  # 07:35 TR sabah
    9: "altcoin ethereum defi guncel",                         # 12:05 TR ogle
    14: "kripto regulasyon makro ekonomi ABD",                  # 17:05 TR aksam
    18: "on-chain whale DeFi likidite akisi kripto yapay zeka AI teknoloji inovasyon uzay",  # 21:35 TR gece
}

# Kesif konusu -> eslesen scanner kategorileri
DISCOVERY_CATEGORIES = {
    4: ["breaking_news", "crypto_analysis", "etf_flows", "macro_economy",
        "tech_news", "geopolitics", "turkey_economy", "energy_commodities", "world_leaders_policy"],
    9: ["crypto_analysis", "data_platforms", "onchain", "ai_crypto"],
    14: ["regulation_web", "macro_economy", "macro_data", "etf_tracking"],
    18: ["whale_onchain", "onchain", "data_platforms", "social_signals",
        "ai_developments", "tech_news", "science_space", "startup_vc"],
}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_recent_findings(conn, hours=LOOKBACK_HOURS):
    """Son N saat icindeki islenmemis onemli bulgulari getir."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute("""
        SELECT id, hash, source_type, source_category, source_name,
               title, snippet, url, relevance_score, created_at, raw_data
        FROM findings
        WHERE processed = 0
          AND created_at >= ?
        ORDER BY relevance_score DESC
    """, (cutoff,)).fetchall()
    return rows


def get_today_xpatla_count(conn):
    """Bugun yapilan XPatla cagrisi sayisi."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT COUNT(DISTINCT topic) FROM xpatla_generations
        WHERE created_at >= ?
    """, (today + "T00:00:00",)).fetchone()
    return row[0] if row else 0


def already_generated(conn, finding_hash):
    """Bu bulgu icin daha once tweet uretilmis mi?"""
    row = conn.execute("""
        SELECT COUNT(*) FROM auto_xpatla_log
        WHERE finding_hash = ?
    """, (finding_hash,)).fetchone()
    return row[0] > 0


def init_auto_log(conn):
    """auto_xpatla_log ve telegram_suggestions tablolarini olustur (yoksa)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_xpatla_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_hash TEXT NOT NULL,
            finding_id INTEGER,
            topic TEXT,
            category TEXT,
            xpatla_called INTEGER DEFAULT 0,
            tweets_generated INTEGER DEFAULT 0,
            telegram_sent INTEGER DEFAULT 0,
            source_type TEXT DEFAULT 'scanner',
            created_at TEXT NOT NULL
        )
    """)
    # Eski tabloya source_type kolonu ekle (yoksa)
    try:
        conn.execute("ALTER TABLE auto_xpatla_log ADD COLUMN source_type TEXT DEFAULT 'scanner'")
    except sqlite3.OperationalError:
        pass  # Kolon zaten var
    # Telegram onerileri tablosu
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            source_url TEXT,
            source_tweet_id TEXT,
            category TEXT,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()


def extract_tweet_id(url):
    """URL'den tweet ID cikar."""
    if not url:
        return None
    match = re.search(r'/status/(\d+)', url)
    return match.group(1) if match else None


def save_suggestion(conn, text, source_url, source_tweet_id, category):
    """Tweet onerisini telegram_suggestions tablosuna kaydet."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute("""
        INSERT INTO telegram_suggestions (text, source_url, source_tweet_id, category, created_at, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (text, source_url, source_tweet_id, category, now))
    conn.commit()
    return cursor.lastrowid


def get_content_age_hours(finding):
    """Icerigin gercek yasini saat cinsinden dondur. None = tarih bulunamadi."""
    raw = finding.get("raw_data")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    now = datetime.now(timezone.utc)

    # Twitter: "created_at": "2026-02-26T01:31:19.000Z"
    if "created_at" in data and isinstance(data["created_at"], str):
        try:
            ct = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            return (now - ct).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    # Web: "age": "12 hours ago", "2 days ago", "34 minutes ago"
    if "age" in data and isinstance(data["age"], str):
        age_str = data["age"].lower()
        try:
            num = int(re.search(r'(\d+)', age_str).group(1))
            if "minute" in age_str:
                return num / 60
            elif "hour" in age_str:
                return float(num)
            elif "day" in age_str:
                return num * 24.0
            elif "week" in age_str:
                return num * 168.0
        except (AttributeError, ValueError):
            pass

    return None


# Icerik yasi limiti (saat) - bundan eski bulgular icin tweet uretme
MAX_CONTENT_AGE_HOURS = 24


def score_finding(finding):
    """Bulguya onem puani ver. Yuksek = daha onemli."""
    score = finding["relevance_score"] or 0
    cat = finding["source_category"]
    priority = CATEGORY_PRIORITY.get(cat, 15)

    # Kategori bonusu (dusuk oncelik = dusuk bonus, kripto her zaman onde)
    cat_bonus = (12 - priority) * 10

    # Baslik uzunlugu bonusu (cok kisa basliklar genelde dusuk kalite)
    title = finding["title"] or ""
    if len(title) > 20:
        cat_bonus += 5

    # Web kaynaklari genelde daha az onemli
    if finding["source_type"] == "web":
        cat_bonus -= 10

    return score + cat_bonus


def extract_topic(finding):
    """Bulgudan XPatla icin konu cikar."""
    title = finding["title"] or ""
    snippet = finding["snippet"] or ""

    # Baslik varsa ve makul uzunluktaysa kullan
    if 10 < len(title) < 100:
        return title.strip()

    # Yoksa snippet'in ilk 100 karakteri
    if snippet:
        text = snippet[:100].strip()
        # Son cumleyi tamamla
        for sep in [".", "!", "?"]:
            idx = text.rfind(sep)
            if idx > 20:
                return text[:idx + 1]
        return text

    return title.strip() or "kripto piyasa"


def group_findings(findings):
    """Iliskili bulgulari kategoriye gore grupla."""
    groups = {}
    for f in findings:
        cat = f.get("source_category", "unknown")
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(f)

    result = []
    for cat, items in groups.items():
        items.sort(key=lambda x: x.get("_score", 0), reverse=True)
        main = items[0]
        context = " | ".join([i.get("title", "")[:50] for i in items[1:3]])
        topic = main.get("title", "")[:200]
        if context:
            topic += f" [Baglam: {context}]"
        result.append({
            "finding": main,
            "topic": topic,
            "category": cat,
            "count": len(items),
            "source_type": "scanner",
        })
    return result


def should_do_discovery():
    """Sabah ve aksam slotlarinda bagimsiz kesif yap."""
    hour = datetime.now(timezone.utc).hour
    return hour < 7 or (17 <= hour < 21)  # Sabah: UTC 4-5 (TR 07-08), Aksam: UTC 18-19 (TR 21-22)


def get_discovery_topic():
    """Saate gore bagimsiz kesif konusu."""
    hour = datetime.now(timezone.utc).hour
    return DISCOVERY_TOPICS.get(hour, "bitcoin kripto piyasa")


def get_time_tone(category_tone):
    """Saate gore tone override (TR saati, UTC+3)."""
    hour = (datetime.now(timezone.utc).hour + 3) % 24
    if hour < 9:       # Sabah - ciddi
        return "polished"
    elif hour < 14:    # Oglen - normal (kategori tone'unu koru)
        return category_tone
    elif hour < 19:    # Aksam - samimi
        return "raw"
    else:              # Gece - kuru
        return "deadpan"


def xpatla_generate(topic, fmt="punch", count=1, persona="authority", tone="default", language="turkish"):
    """XPatla API'den tweet uret."""
    if not XPATLA_API_KEY:
        print("[HATA] XPATLA_API_KEY ayarlanmamis!")
        return None

    headers = {
        "Authorization": f"Bearer {XPATLA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "twitter_username": TWITTER_USERNAME,
        "topic": topic,
        "format": fmt,
        "count": count,
        "persona": persona,
        "tone": tone,
        "language": language,
        "apex_mode": True,
    }

    try:
        resp = requests.post(
            f"{XPATLA_BASE_URL}/tweets/generate",
            headers=headers, json=payload, timeout=60
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"[HATA] XPatla API: {resp.status_code} - {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"[HATA] XPatla istek hatasi: {e}")
        return None


def save_xpatla_result(conn, topic, fmt, persona, tone, tweets, credits_used, remaining):
    """XPatla sonuclarini xpatla_generations tablosuna kaydet."""
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for t in tweets:
        text = t.get("text", "")
        if not text:
            continue
        tweet_hash = hashlib.md5(text.encode()).hexdigest()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO xpatla_generations
                (created_at, endpoint, topic, format, persona, tone, tweet_text, angle,
                 char_count, image_url, credits_used, remaining_credits, tweet_hash)
                VALUES (?, '/tweets/generate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (now, topic, fmt, persona, tone, text, t.get("angle", ""),
                  t.get("char_count", len(text)), t.get("generated_image_url"),
                  credits_used, remaining, tweet_hash))
            saved += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return saved



def is_duplicate_topic(conn, topic_text, hours=24):
    """Son X saat icinde benzer konuda tweet uretilmis mi kontrol et."""
    import difflib
    recent = conn.execute(
        "SELECT text FROM telegram_suggestions WHERE created_at >= datetime('now', '-' || ? || ' hours') AND status IN ('pending', 'sent')",
        (str(hours),)
    ).fetchall()
    for row in recent:
        ratio = difflib.SequenceMatcher(None, topic_text.lower()[:100], row[0].lower()[:100]).ratio()
        if ratio > 0.6:
            print("  [DEDUP] Benzer icerik zaten var (benzerlik: %.0f%%)" % (ratio * 100))
            return True
    return False

def send_telegram(message, parse_mode="HTML", reply_markup=None):
    """Telegram'a mesaj gonder, opsiyonel inline keyboard ile."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[UYARI] Telegram bilgileri eksik")
        return False
    if len(message) > 4000:
        message = message[:4000] + "\n... (kesildi)"
    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[UYARI] Telegram hatasi: {e}")
        return False


def format_telegram_message(finding, tweets, credits_used, remaining, source_type="scanner", suggestion_ids=None):
    """Telegram mesajini formatla."""
    # Kaynak gostergesi
    if source_type == "discovery":
        source_icon = "\U0001f50d XPatla Kesfi"
    elif source_type == "merged":
        source_icon = "\U0001f517 Harmanlanmis Bulgu"
    else:
        source_icon = "\U0001f4e1 Scanner Bulgusu"

    if finding:
        cat = finding.get("source_category", "")
        title = finding.get("title", "") or ""
        url = finding.get("url", "") or ""
        source = finding.get("source_name", "") or ""
    else:
        cat = "discovery"
        title = ""
        url = ""
        source = "XPatla"

    lines = [
        f"{source_icon}",
        f"\U0001f4cc <i>{cat}</i> | {source}",
    ]
    if title:
        lines.append(f"\U0001f4f0 {title[:150]}")
    if url:
        lines.append(f"\U0001f517 {url}")
    lines.append("")

    for i, t in enumerate(tweets):
        text = t.get("text", "")
        angle = t.get("angle", "")
        chars = t.get("char_count", t.get("character_count", len(text)))
        # Suggestion ID varsa onu kullan, yoksa siralama numarasi
        sid = suggestion_ids[i] if suggestion_ids and i < len(suggestion_ids) else i + 1
        hdr = f"<b>#{sid}</b>"
        if angle:
            hdr += f" [{angle}]"
        hdr += f" ({chars} chr)"
        lines.append(hdr)
        lines.append(f"<code>{text}</code>")
        lines.append(f"\u26a1 <code>at {sid}</code> \u00b7 <code>atma {sid}</code> \u00b7 <code>d\u00fczenle {sid}: metin</code>")
        lines.append("")

    lines.append(f"\U0001f4b0 -{credits_used} kredi | Kalan: {remaining}")

    return "\n".join(lines)


def send_weekly_credit_report(conn):
    """Pazartesi gunu haftalik kredi raporu gonder."""
    if datetime.now().weekday() != 0:  # 0 = Pazartesi
        return

    # Bu haftanin kredi kullanimi
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT COALESCE(SUM(credits_used), 0) as total_used
        FROM xpatla_generations
        WHERE created_at >= ?
    """, (week_start + "T00:00:00",)).fetchone()
    weekly_used = row[0] if row else 0

    # Kalan kredi (en son kayittan)
    row2 = conn.execute("""
        SELECT remaining_credits FROM xpatla_generations
        ORDER BY created_at DESC LIMIT 1
    """).fetchone()
    remaining = row2[0] if row2 and row2[0] else 0
    if remaining <= 0:
        # XPatla API'den gercek bakiyeyi cek
        try:
            import requests
            api_key = os.environ.get("XPATLA_API_KEY", "")
            if api_key:
                r = requests.get("https://xpatla.com/api/v1/credits/balance",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    remaining = data.get("data", {}).get("credits_balance", 0)
                    print(f"[BILGI] XPatla API bakiye: {remaining} kredi")
        except Exception as e:
            print(f"[UYARI] XPatla bakiye sorgusu basarisiz: {e}")
        if remaining <= 0:
            remaining = 500  # Son fallback: muhafazakar tahmin

    # Ay sonuna kalan gun ve gunluk butce
    today = datetime.now()
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1)
    days_left = (month_end - today).days or 1
    daily_budget = remaining / days_left

    msg = (
        f"\U0001f4ca <b>Haftalik XPatla Kredi Raporu</b>\n\n"
        f"\U0001f4b8 Bu hafta harcanan: <b>{weekly_used}</b> kredi\n"
        f"\U0001f4b0 Kalan kredi: <b>{remaining}</b>\n"
        f"\U0001f4c5 Ay sonuna <b>{days_left}</b> gun\n"
        f"\U0001f4cc Gunluk butce: <b>{daily_budget:.1f}</b> kredi/gun\n"
    )
    send_telegram(msg)
    print(f"[BILGI] Haftalik kredi raporu gonderildi (haftalik: {weekly_used}, kalan: {remaining})")



def get_cooldown_remaining():
    """Son auto-approve'dan bu yana kalan cooldown suresini dakika olarak dondur. 0 = hazir."""
    import random
    try:
        with open(COOLDOWN_FILE, "r") as f:
            parts = f.read().strip().split("|")
            last_ts = float(parts[0])
            cooldown_mins = int(parts[1]) if len(parts) > 1 else random.randint(COOLDOWN_MIN_MINUTES, COOLDOWN_MAX_MINUTES)
    except (FileNotFoundError, ValueError):
        return 0
    elapsed = (datetime.now(timezone.utc).timestamp() - last_ts) / 60.0
    remaining = cooldown_mins - elapsed
    return max(0, remaining)


def set_cooldown():
    """Yeni cooldown baslat."""
    import random
    cooldown_mins = random.randint(COOLDOWN_MIN_MINUTES, COOLDOWN_MAX_MINUTES)
    ts = datetime.now(timezone.utc).timestamp()
    with open(COOLDOWN_FILE, "w") as f:
        f.write("%f|%d" % (ts, cooldown_mins))
    return cooldown_mins


def main():
    parser = argparse.ArgumentParser(description="Otomatik XPatla Tweet Onerisi")
    parser.add_argument("--dry-run", action="store_true", help="Test modu (API cagirmaz)")
    parser.add_argument("--force", action="store_true", help="Gunluk limiti gormezden gel")
    parser.add_argument("--hours", type=float, default=LOOKBACK_HOURS, help="Kac saat geriye bak")
    args = parser.parse_args()

    print(f"[BASLA] auto_xpatla.py - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    conn = get_db()
    init_auto_log(conn)

    # Pazartesi ise haftalik kredi raporu gonder
    send_weekly_credit_report(conn)

    # Gunluk XPatla cagrisi kontrolu
    today_count = get_today_xpatla_count(conn)
    remaining_calls = DAILY_MAX_CALLS - today_count
    print(f"[BILGI] Bugun {today_count} XPatla cagrisi yapildi, {remaining_calls} kaldi")

    if remaining_calls <= 0 and not args.force:
        print(f"[BILGI] Gunluk limit ({DAILY_MAX_CALLS}) doldu. --force ile zorla.")
        conn.close()
        return

    # Son bulgulari al
    findings = get_recent_findings(conn, args.hours)
    print(f"[BILGI] Son {args.hours} saat icinde {len(findings)} islenmemis bulgu")

    # Bulgulari skorla ve filtrele
    scored = []
    skipped_old = 0
    for f in findings:
        fdict = dict(f)
        if already_generated(conn, fdict["hash"]):
            continue
        # Icerik yasi kontrolu - eski haberleri/tweetleri atla
        age_hours = get_content_age_hours(fdict)
        if age_hours is not None and age_hours > MAX_CONTENT_AGE_HOURS:
            skipped_old += 1
            print(f"[ATLA] Eski icerik ({age_hours:.0f}h): {fdict.get('title', '')[:60]}")
            continue
        fdict["_score"] = score_finding(fdict)
        scored.append(fdict)

    if skipped_old:
        print(f"[BILGI] {skipped_old} bulgu icerik yasi >{MAX_CONTENT_AGE_HOURS}h oldugu icin atildi")
    scored.sort(key=lambda x: x["_score"], reverse=True)

    # Slot-bazli kategori filtreleme
    tweet_slot = os.environ.get("TWEET_SLOT", "")
    if tweet_slot and tweet_slot in SLOT_CATEGORY_MAP:
        preferred_cats = SLOT_CATEGORY_MAP[tweet_slot]
        slot_findings = [f for f in scored if f["source_category"] in preferred_cats]
        other_findings = [f for f in scored if f["source_category"] not in preferred_cats]
        if slot_findings:
            scored = slot_findings + other_findings
            print("[SLOT] %s: %d preferred bulgu one alindi" % (tweet_slot, len(slot_findings)))
        else:
            print("[SLOT] %s: preferred bulgu yok, tum bulgular kullaniliyor" % tweet_slot)
    elif tweet_slot:
        print("[SLOT] %s: bilinmeyen slot, tum bulgular kullaniliyor" % tweet_slot)

    print(f"[BILGI] {len(scored)} yeni bulgu (daha once uretilmemis, icerik taze)")

    # Dusuk skorlu bulgulari filtrele
    candidates = [f for f in scored if f["_score"] >= MIN_RELEVANCE_SCORE]
    print(f"[BILGI] {len(candidates)} bulgu minimum skor ({MIN_RELEVANCE_SCORE}) uzerinde")

    # Bulgulari grupla
    groups = group_findings(candidates) if candidates else []

    # Bagimsiz kesif kontrolu (sadece sabah slotunda)
    do_discovery = should_do_discovery()
    if do_discovery:
        discovery_topic = get_discovery_topic()
        hour = datetime.now(timezone.utc).hour
        matching_cats = DISCOVERY_CATEGORIES.get(hour, [])

        # Scanner gruplariyla eslestirmeyi dene
        merged = False
        for g in groups:
            if g["category"] in matching_cats:
                g["topic"] = f"{g['topic']} | Genel trend: {discovery_topic}"
                g["source_type"] = "merged"
                merged = True
                print(f"[BILGI] Kesif konusu -> {g['category']} ile harmanlandi")
                break

        if not merged:
            # Eslesen grup yok, ayri kesif ekle
            groups.append({
                "finding": None,
                "topic": discovery_topic,
                "category": "discovery",
                "count": 0,
                "source_type": "discovery",
            })
            print(f"[BILGI] Bagimsiz kesif eklendi: {discovery_topic}")

    if not groups and scored:
        # Skor dusuk ama bulgu var, en iyisini al
        best = scored[0]
        topic = extract_topic(best)
        groups = [{
            "finding": best,
            "topic": topic,
            "category": best["source_category"],
            "count": 1,
            "source_type": "scanner",
        }]
        print(f"[BILGI] Skor dusuk, en iyi bulgu alinacak (skor: {best['_score']})")

    if not groups:
        if findings and not scored:
            print("[BILGI] Tum bulgular icin daha once tweet uretilmis.")
        else:
            print("[BILGI] Yeni bulgu yok, cikiliyor.")
        conn.close()
        return

    # Oncelikli sirala (yuksek oncelikli kategoriler once)
    groups.sort(key=lambda g: CATEGORY_PRIORITY.get(g["category"], 10))

    # Kalan cagri sayisi kadar isle
    to_process = groups[:remaining_calls] if remaining_calls > 0 else groups[:2]  # Fallback: en az 2 grup isle  # --force: en az 1 grup isle
    print(f"[BILGI] {len(to_process)} grup icin tweet uretilecek")

    generated_count = 0
    auto_candidates = []  # Auto-approve adaylari
    for group in to_process:
        topic = group["topic"]
        cat = group["category"]
        finding = group["finding"]
        source_type = group.get("source_type", "scanner")

        # Kategori config'den format/persona/tone al
        config = CATEGORY_CONFIG.get(cat, DEFAULT_CONFIG)
        fmt = config["format"]
        persona = config["persona"]
        tone = config["tone"]

        # Saate gore tone override
        tone = get_time_tone(tone)

        # Kategoriye gore dil secimi
        language = "english" if cat in ENGLISH_CATEGORIES else "turkish"

        # Kesif icin ozel config
        if source_type == "discovery":
            fmt = "spark"
            persona = "authority"
            tone = get_time_tone("polished")
            language = "turkish"

        finding_id = finding["id"] if finding else None
        finding_score = finding.get("_score", 0) if finding else 0

        print(f"\n[ISLEM] {cat} | kaynak={source_type} | {group['count']} bulgu | skor={finding_score}")
        print(f"  Konu: {topic[:80]}")
        # Duplikat kontrolu
        if is_duplicate_topic(conn, topic):
            print("  [SKIP] Benzer konu zaten uretilmis, atlaniyor")
            continue

        print(f"  Format: {fmt} | Persona: {persona} | Tone: {tone} | Dil: {language}")

        now = datetime.now(timezone.utc).isoformat()
        finding_hash = finding["hash"] if finding else hashlib.md5(topic.encode()).hexdigest()

        if args.dry_run:
            print("  [DRY-RUN] XPatla API cagrilmadi")
            conn.execute("""
                INSERT INTO auto_xpatla_log
                (finding_hash, finding_id, topic, category, xpatla_called, source_type, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
            """, (finding_hash, finding_id, topic, cat, source_type, now))
            conn.commit()
            continue

        # XPatla API cagir
        result = xpatla_generate(topic, fmt, TWEETS_PER_FINDING, persona, tone, language)
        if not result or not result.get("success"):
            print("  [HATA] XPatla basarisiz")
            conn.execute("""
                INSERT INTO auto_xpatla_log
                (finding_hash, finding_id, topic, category, xpatla_called, source_type, created_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """, (finding_hash, finding_id, topic, cat, source_type, now))
            conn.commit()
            continue

        data = result.get("data", result)
        tweets = data.get("tweets", [])
        credits_used = result.get("credits_used", 0)
        remaining_credits = result.get("remaining_credits", 0)

        # Kaydet
        saved = save_xpatla_result(conn, topic, fmt, persona, tone, tweets, credits_used, remaining_credits)
        print(f"  [OK] {len(tweets)} tweet uretildi ({saved} yeni)")

        # Onerileri validate et ve telegram_suggestions tablosuna kaydet
        suggestion_ids = []
        source_url = finding.get("url") if finding else None
        source_tweet_id = extract_tweet_id(source_url)
        source_content = None
        if finding:
            source_content = finding.get("title", "") or ""
            snippet = finding.get("snippet", "") or ""
            if snippet:
                source_content += " | " + snippet

        validated_tweets = []
        for t in tweets:
            text = t.get("text", "")
            if not text:
                continue

            # Kalite kontrolu: gramer + yabanci kelime ekleri + icerik dogrulugu
            if not args.dry_run:
                vresult = validate_tweet(text, source_content)
                issues = vresult.get("issues", [])
                acc = vresult.get("accuracy_score", 80)
                corrected = vresult.get("corrected_text", text)

                if acc < 70:
                    print("  [REJECT] accuracy_score=%d < 70, tweet reddedildi" % acc)
                    if issues:
                        print("  [REJECT] Sorunlar: %s" % "; ".join(issues[:3]))
                    continue

                if corrected and corrected != text:
                    print("  [DUZELTME] Tweet duzeltildi")
                    t["text"] = corrected
                    t["_corrected"] = True
                    text = corrected

                if issues:
                    print("  [VALIDATOR] %s" % "; ".join(issues[:3]))

            sid = save_suggestion(conn, text, source_url, source_tweet_id, cat)
            suggestion_ids.append(sid)
            validated_tweets.append(t)
            corrected_tag = " [duzeltildi]" if t.get("_corrected") else ""
            print(f"  [ONERI] #{sid} kaydedildi{corrected_tag}")

        tweets = validated_tweets

        # Telegram'a gonder (inline butonlarla)
        # Duzeltilmis tweetlere tag ekle
        for t in tweets:
            if t.get("_corrected"):
                t["angle"] = (t.get("angle", "") + " [duzeltildi]").strip()
        tg_msg = format_telegram_message(finding, tweets, credits_used, remaining_credits, source_type, suggestion_ids)
        # Her oneri icin buton olustur
        reply_markup = None
        if suggestion_ids:
            buttons = []
            for sid in suggestion_ids:
                row = [
                    {"text": "\u2705 Onayla", "callback_data": f"at_{sid}"},
                    {"text": "\u274c Reddet", "callback_data": f"atma_{sid}"},
                    {"text": "\u270f\ufe0f D\u00fczenle", "callback_data": f"duzenle_{sid}"},
                ]
                if source_tweet_id:
                    row.append({"text": "\U0001f4ac Quote", "callback_data": f"quote_{sid}"})
                buttons.append(row)
            reply_markup = {"inline_keyboard": buttons}
        tg_ok = send_telegram(tg_msg, reply_markup=reply_markup)
        print(f"  [TELEGRAM] {'Gonderildi' if tg_ok else 'Gonderilemedi'}")

        # === AUTO-APPROVE ADAY TOPLAMA ===
        if AUTO_APPROVE_ENABLED and suggestion_ids:
            try:
                f_score = finding.get("relevance_score", 0) if isinstance(finding, dict) else 0
            except Exception:
                f_score = 0

            if f_score >= AUTO_APPROVE_SCORE:
                auto_candidates.append({
                    "suggestion_id": suggestion_ids[0],
                    "f_score": f_score,
                    "source_tweet_id": source_tweet_id,
                    "has_quote": bool(source_tweet_id),
                    "created_at": now,
                })
                print("  [AUTO-ADAY] Skor %d >= %d, aday listesine eklendi" % (f_score, AUTO_APPROVE_SCORE))
            else:
                print("  [MANUEL] Skor %d < %d, Telegram onayi bekleniyor" % (f_score, AUTO_APPROVE_SCORE))

        # Log kaydet
        conn.execute("""
            INSERT INTO auto_xpatla_log
            (finding_hash, finding_id, topic, category, xpatla_called,
             tweets_generated, telegram_sent, source_type, created_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (finding_hash, finding_id, topic, cat,
              len(tweets), 1 if tg_ok else 0, source_type, now))
        conn.commit()

        generated_count += 1

    # === AUTO-APPROVE ONCELIKLENDIRME + COOLDOWN ===
    if auto_candidates:
        # Sirala: quote tweet > yuksek skor > taze haber
        auto_candidates.sort(key=lambda c: (c["has_quote"], c["f_score"]), reverse=True)
        best = auto_candidates[0]
        rest = auto_candidates[1:]

        print(f"\n[AUTO-PRIORITY] {len(auto_candidates)} aday icinden en iyi secildi: "
              f"score={best['f_score']}, quote={best['has_quote']}")
        if rest:
            print(f"  [AUTO-PRIORITY] {len(rest)} aday Telegram onayi bekleyecek")

        # Cooldown kontrolu
        cd_remaining = get_cooldown_remaining()
        if cd_remaining > 0:
            print("  [COOLDOWN] Aktif, %d dk kaldi. Telegram'a gonderiliyor" % int(cd_remaining))
        else:
            # Auto-approve en iyi adayi
            suggestion_id = best["suggestion_id"]
            source_tweet_id = best["source_tweet_id"]
            print("  [AUTO-APPROVE] #%d atiliyor (score=%d)" % (suggestion_id, best["f_score"]))

            import time as _time
            _time.sleep(2)

            if source_tweet_id:
                cmd = "quote %d" % suggestion_id
                print("  [AUTO-QUOTE] Quote tweet olarak atiliyor (source: %s)" % source_tweet_id)
            else:
                cmd = "at %d" % suggestion_id
                print("  [AUTO-TWEET] Normal tweet olarak atiliyor")

            try:
                import subprocess as _sp
                result = _sp.run(
                    ["python3", "telegram_commands.py", cmd],
                    capture_output=True, text=True, timeout=30,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    env={**os.environ}
                )
                out = (result.stdout or "") + (result.stderr or "")
                if "Tweet posted" in out or "atildi" in out:
                    cooldown_mins = set_cooldown()
                    if "fallback" in out.lower():
                        print("  [AUTO] Tweet #%d fallback ile atildi! Cooldown: %d dk" % (suggestion_id, cooldown_mins))
                    else:
                        print("  [AUTO] Tweet #%d basariyla atildi! Cooldown: %d dk" % (suggestion_id, cooldown_mins))
                else:
                    print("  [AUTO] Sonuc: %s" % out.strip()[:150])
            except Exception as e:
                print("  [AUTO] Hata: %s" % e)

    print(f"\n[SONUC] {generated_count} grup icin tweet uretildi")
    conn.close()
    print("[BITTI]")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_error_alert("auto_xpatla", str(e))
        raise
