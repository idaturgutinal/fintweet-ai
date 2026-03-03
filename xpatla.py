#!/usr/bin/env python3
"""
XPatla API Integration for FinTweet AI
======================================
@equinoxistr | Kripto/Finans Twitter Botu

XPatla API ile viral tweet üretme, quote tweet önerisi, reply önerisi
ve kredi bakiye kontrolü.

Kullanım:
  python3 xpatla.py --generate "bitcoin" --format punch --count 3
  python3 xpatla.py --generate "ethereum" --format classic --persona news --tone raw
  python3 xpatla.py --generate "yapay zeka" --image
  python3 xpatla.py --quote "AI is changing everything" --author elonmusk
  python3 xpatla.py --reply "Building in public is overrated" --author levelsio --reply-tone insightful
  python3 xpatla.py --credits
  python3 xpatla.py --telegram --generate "bitcoin"

Ortam Değişkenleri (~/.fintweet-env):
  XPATLA_API_KEY=xp_live_YOUR_KEY
"""

import os
import sys
import json
import argparse
import requests
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import anthropic

# ─── Ortam değişkenlerini yükle ─────────────────────────────────────
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

# ─── Sabitler ────────────────────────────────────────────────────────
XPATLA_BASE_URL = "https://xpatla.com/api/v1"
XPATLA_API_KEY = os.environ.get("XPATLA_API_KEY", "")
TWITTER_USERNAME = "equinoxistr"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DB_PATH = os.path.expanduser("~/.openclaw/workspace/fintweet.db")

VALID_FORMATS = ["micro", "punch", "classic", "spark", "storm", "longform", "thunder", "mega"]
VALID_PERSONAS = ["authority", "news", "shitpost", "mentalist", "bilgi", "sigma", "doomer", "hustler"]
VALID_TONES = ["default", "raw", "polished", "unhinged", "deadpan"]
VALID_REPLY_TONES = ["supportive", "witty", "insightful", "provocative"]
VALID_LANGUAGES = ["turkish", "english"]
VALID_IMAGE_STYLES = ["landscape_16_9", "square", "portrait_4_3"]

CREDIT_TABLE = {
    "punch": 3, "spark": 5, "storm": 7, "thunder": 10,
    "micro": 3, "classic": 3, "longform": 10, "mega": 10,
    "quote": 6, "reply": 6, "image": 5
}

# ─── Claude API Fallback ────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SOUL_PATH = os.path.expanduser("~/.openclaw/workspace/SOUL.md")
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"


def claude_generate_tweet(topic, fmt="punch", persona="authority", tone="default", language="turkish"):
    """XPatla basarisiz oldugunda Claude API ile tweet uret."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "PLACEHOLDER":
        print("[HATA] ANTHROPIC_API_KEY ayarlanmamis!")
        return None

    # SOUL.md oku
    soul_content = ""
    try:
        with open(SOUL_PATH, "r") as f:
            soul_content = f.read()
    except FileNotFoundError:
        print("[UYARI] SOUL.md bulunamadi, varsayilan prompt kullaniliyor")

    system_prompt = soul_content if soul_content else "Sen @equinoxistr icin Turkce kripto/finans tweeti yazan bir AI'sin."

    lang_instruction = "Turkce yaz." if language == "turkish" else "Write in English."

    user_prompt = f"""Asagidaki konu hakkinda TEK bir tweet yaz.

Konu: {topic}
Format: {fmt}
Persona: {persona}
Ton: {tone}
Dil: {lang_instruction}

KURALLAR:
- SADECE tweet metnini yaz, baska HICBIR SEY yazma
- Tirnak isareti, baslik, aciklama, etiket EKLEME
- Tweet 280 karakteri ASLA gecmesin
- SOUL.md'deki format/persona/ton tanimina uy
"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        text = response.content[0].text.strip()
        # Baslangic/bitis tirnak isaretlerini temizle
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("‘") or text.startswith("“"):
            text = text[1:]
        if text.endswith("’") or text.endswith("”"):
            text = text[:-1]
        text = text.strip()
        if len(text) > 280:
            text = text[:277] + "..."
        return {"text": text, "angle": "claude-fallback", "char_count": len(text)}
    except Exception as e:
        print(f"[HATA] Claude API basarisiz: {e}")
        return None


# ─── Yardımcı Fonksiyonlar ──────────────────────────────────────────

def xpatla_headers():
    if not XPATLA_API_KEY:
        print("❌ XPATLA_API_KEY ayarlanmamış!")
        print("   ~/.fintweet-env dosyasına ekle: export XPATLA_API_KEY=xp_live_YOUR_KEY")
        sys.exit(1)
    return {
        "Authorization": f"Bearer {XPATLA_API_KEY}",
        "Content-Type": "application/json"
    }


def xpatla_request(method, endpoint, data=None):
    url = f"{XPATLA_BASE_URL}{endpoint}"
    try:
        if method == "GET":
            resp = requests.get(url, headers=xpatla_headers(), timeout=60)
        else:
            resp = requests.post(url, headers=xpatla_headers(), json=data, timeout=60)

        if resp.status_code == 200:
            return resp.json()

        error_map = {
            400: "Geçersiz istek parametreleri (bad_request)",
            401: "Geçersiz/eksik API anahtarı (invalid_api_key)",
            402: "Yetersiz kredi (insufficient_credits)",
            403: "Bu hesaba erişim yok (account_not_owned)",
            429: "Rate limit aşıldı - 30/dk veya 1000/gün (rate_limit_exceeded)"
        }
        desc = error_map.get(resp.status_code, f"HTTP {resp.status_code}")
        detail = ""
        try:
            detail = resp.json().get("error", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        print(f"❌ {desc}: {detail}")
        return None

    except requests.exceptions.Timeout:
        print("❌ Zaman aşımı (30s)")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ Bağlantı hatası")
        return None
    except Exception as e:
        print(f"❌ Hata: {e}")
        return None


def send_telegram(message, parse_mode="HTML"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram bilgileri eksik")
        return False
    if len(message) > 4000:
        message = message[:4000] + "\n... (kesildi)"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, "text": message,
            "parse_mode": parse_mode, "disable_web_page_preview": True
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"⚠️  Telegram hatası: {e}")
        return False


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS xpatla_generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            topic TEXT,
            format TEXT,
            persona TEXT,
            tone TEXT,
            tweet_text TEXT,
            angle TEXT,
            char_count INTEGER,
            image_url TEXT,
            credits_used INTEGER,
            remaining_credits INTEGER,
            tweet_hash TEXT UNIQUE
        )
    """)
    conn.commit()
    conn.close()


def save_generation(endpoint, topic, fmt, persona, tone, tweets, credits_used, remaining):
    conn = sqlite3.connect(DB_PATH)
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (now, endpoint, topic, fmt, persona, tone, text,
                  t.get("angle", ""), t.get("char_count", t.get("character_count", len(text))),
                  t.get("generated_image_url"), credits_used, remaining, tweet_hash))
            saved += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return saved


# ─── API Fonksiyonları ───────────────────────────────────────────────

def generate_tweets(topic, fmt="punch", count=3, persona="authority", tone="default",
                    language="turkish", apex_mode=True, generate_image=False,
                    image_style="landscape_16_9"):
    """POST /tweets/generate"""
    payload = {
        "twitter_username": TWITTER_USERNAME,
        "topic": topic,
        "format": fmt,
        "count": min(max(count, 1), 10),
        "persona": persona,
        "tone": tone,
        "language": language,
        "apex_mode": apex_mode,
    }
    if generate_image:
        payload["generate_image"] = True
        payload["image_style"] = image_style

    est = CREDIT_TABLE.get(fmt, 3) * payload["count"]
    if generate_image:
        est += 5 * payload["count"]
    print(f"🔄 Tweet üretiliyor: \"{topic}\" | {fmt}/{persona}/{tone} | ~{est} kredi")

    result = xpatla_request("POST", "/tweets/generate", payload)
    if result and result.get("success"):
        data = result.get("data", result)
        tweets = data.get("tweets", [])
        cu = result.get("credits_used", 0)
        rem = result.get("remaining_credits", 0)
        saved = save_generation("/tweets/generate", topic, fmt, persona, tone, tweets, cu, rem)
        print(f"✅ {len(tweets)} tweet üretildi ({saved} yeni) | -{cu} kredi (Kalan: {rem})")
        return {"success": True, "tweets": tweets, "credits_used": cu, "remaining_credits": rem}

    # ─── Claude API Fallback ────────────────────────────────────
    print("[FALLBACK] XPatla basarisiz, Claude API kullaniliyor")
    claude_tweets = []
    for i in range(min(max(count, 1), 10)):
        tweet = claude_generate_tweet(topic, fmt, persona, tone, language)
        if tweet:
            claude_tweets.append(tweet)
    if not claude_tweets:
        print("[HATA] Claude API de basarisiz")
        return None
    saved = save_generation("/tweets/generate", topic, fmt, persona, tone, claude_tweets, 0, 0)
    print(f"✅ {len(claude_tweets)} tweet üretildi (Claude fallback, {saved} yeni)")
    return {"success": True, "tweets": claude_tweets, "credits_used": 0, "remaining_credits": 0}


def generate_quote(tweet_text, tweet_author, fmt="punch", count=3):
    """POST /quotes/generate"""
    tweet_author = tweet_author.lstrip("@")
    payload = {
        "twitter_username": TWITTER_USERNAME,
        "original_tweet": {
            "text": tweet_text,
            "author": tweet_author
        },
        "format": fmt,
        "count": min(max(count, 1), 5)
    }
    print(f"🔄 Quote üretiliyor: @{tweet_author} → \"{tweet_text[:50]}...\"")

    result = xpatla_request("POST", "/quotes/generate", payload)
    if not result or not result.get("success"):
        return None

    tweets = result.get("tweets", result.get("quotes", []))
    if not isinstance(tweets, list):
        tweets = [tweets]
    cu = result.get("credits_used", 0)
    rem = result.get("remaining_credits", 0)
    save_generation("/quotes/generate", f"quote @{tweet_author}", fmt, None, None, tweets, cu, rem)
    print(f"✅ {len(tweets)} quote üretildi | -{cu} kredi (Kalan: {rem})")
    return {"success": True, "tweets": tweets, "credits_used": cu, "remaining_credits": rem}


def generate_reply(tweet_text, tweet_author, reply_tone="supportive", count=3):
    """POST /replies/generate"""
    tweet_author = tweet_author.lstrip("@")
    payload = {
        "twitter_username": TWITTER_USERNAME,
        "original_tweet_text": tweet_text,
        "original_tweet_author": tweet_author,
        "tone": reply_tone,
        "count": min(max(count, 1), 5)
    }
    print(f"🔄 Reply üretiliyor: @{tweet_author} (tone={reply_tone})")

    result = xpatla_request("POST", "/replies/generate", payload)
    if not result or not result.get("success"):
        return None

    tweets = result.get("tweets", result.get("replies", []))
    if not isinstance(tweets, list):
        tweets = [tweets]
    cu = result.get("credits_used", 0)
    rem = result.get("remaining_credits", 0)
    save_generation("/replies/generate", f"reply @{tweet_author}", None, None, reply_tone, tweets, cu, rem)
    print(f"✅ {len(tweets)} reply üretildi | -{cu} kredi (Kalan: {rem})")
    return {"success": True, "tweets": tweets, "credits_used": cu, "remaining_credits": rem}


def check_credits():
    """GET /credits/balance"""
    print("🔄 Kredi bakiyesi kontrol ediliyor...")
    result = xpatla_request("GET", "/credits/balance")
    if result:
        print(f"💰 {json.dumps(result, indent=2, ensure_ascii=False)}")
    return result


# ─── Çıktı Formatlama ───────────────────────────────────────────────

def format_console(result, label="Tweet"):
    tweets = result.get("tweets", result.get("quotes", result.get("replies", [])))
    if not isinstance(tweets, list):
        tweets = [tweets]
    out = []
    for i, t in enumerate(tweets, 1):
        text = t.get("text", "")
        angle = t.get("angle", "")
        chars = t.get("char_count", t.get("character_count", len(text)))
        media = t.get("suggested_media")
        img = t.get("generated_image_url")

        out.append(f"\n{'─'*55}")
        hdr = f"  {label} {i}"
        if angle:
            hdr += f" | {angle}"
        hdr += f" | {chars} chr"
        out.append(hdr)
        out.append(f"{'─'*55}")
        out.append(f"  {text}")
        if media and media.get("suggestion"):
            out.append(f"  📸 {media['suggestion']}")
        if img:
            out.append(f"  🖼️  {img}")

    cu = result.get("credits_used", 0)
    rem = result.get("remaining_credits", 0)
    out.append(f"\n💰 -{cu} kredi | Kalan: {rem}")
    return "\n".join(out)


def format_telegram(result, title="Tweet Önerileri", topic=""):
    tweets = result.get("tweets", result.get("quotes", result.get("replies", [])))
    if not isinstance(tweets, list):
        tweets = [tweets]
    lines = [f"🚀 <b>XPatla {title}</b>"]
    if topic:
        lines.append(f"📌 <i>{topic}</i>")
    lines.append("")
    for i, t in enumerate(tweets, 1):
        text = t.get("text", "")
        angle = t.get("angle", "")
        chars = t.get("char_count", t.get("character_count", len(text)))
        img = t.get("generated_image_url")
        hdr = f"<b>#{i}</b>"
        if angle:
            hdr += f" [{angle}]"
        hdr += f" ({chars} chr)"
        lines.append(hdr)
        lines.append(f"<code>{text}</code>")
        if img:
            lines.append(f"🖼️ <a href=\"{img}\">Görsel</a>")
        lines.append("")
    cu = result.get("credits_used", 0)
    rem = result.get("remaining_credits", 0)
    lines.append(f"💰 -{cu} kredi | Kalan: {rem}")
    lines.append("")
    lines.append("<i>Beğendiğini at:</i>")
    lines.append("<code>python3 tweet.py \"METİN\"</code>")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="XPatla API - FinTweet AI Entegrasyonu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  python3 xpatla.py --generate "bitcoin" --format punch --count 3
  python3 xpatla.py --generate "ethereum" --persona news --tone raw
  python3 xpatla.py --generate "yapay zeka" --image
  python3 xpatla.py --quote "AI is changing everything" --author elonmusk
  python3 xpatla.py --quote "BTC 100k" --author Bitcoin_Archive --format spark
  python3 xpatla.py --reply "Building in public" --author levelsio --reply-tone insightful
  python3 xpatla.py --credits
  python3 xpatla.py --telegram --generate "bitcoin"

Kredi: Punch=3 | Spark=5 | Storm=7 | Thunder=10 | Quote=6 | Reply=6 | Görsel=+5
        """)

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--generate", metavar="KONU", help="Tweet üret")
    action.add_argument("--quote", metavar="TWEET_METNİ", help="Quote tweet üret")
    action.add_argument("--reply", metavar="TWEET_METNİ", help="Reply üret")
    action.add_argument("--credits", action="store_true", help="Kredi bakiyesi")

    parser.add_argument("--format", "-f", choices=VALID_FORMATS, default="punch")
    parser.add_argument("--count", "-n", type=int, default=3)
    parser.add_argument("--persona", "-p", choices=VALID_PERSONAS, default="authority")
    parser.add_argument("--tone", "-t", choices=VALID_TONES, default="default")
    parser.add_argument("--language", "-l", choices=VALID_LANGUAGES, default="turkish")
    parser.add_argument("--no-apex", action="store_true")
    parser.add_argument("--image", action="store_true", help="+5 kredi/tweet")
    parser.add_argument("--image-style", choices=VALID_IMAGE_STYLES, default="landscape_16_9")
    parser.add_argument("--author", "-a", metavar="USERNAME", help="Tweet sahibi (quote/reply için)")
    parser.add_argument("--reply-tone", choices=VALID_REPLY_TONES, default="supportive")
    parser.add_argument("--telegram", action="store_true", help="Telegram'a gönder")
    parser.add_argument("--json", action="store_true", help="JSON çıktı")

    args = parser.parse_args()
    init_db()

    if args.credits:
        result = check_credits()
        if result and args.telegram:
            send_telegram(f"💰 <b>XPatla Kredi</b>\n<pre>{json.dumps(result, indent=2, ensure_ascii=False)}</pre>")
        return

    if args.generate:
        result = generate_tweets(args.generate, args.format, args.count, args.persona,
                                 args.tone, args.language, not args.no_apex,
                                 args.image, args.image_style)
        if result:
            print(format_console(result, "Tweet")) if not args.json else print(json.dumps(result, indent=2, ensure_ascii=False))
            if args.telegram:
                send_telegram(format_telegram(result, "Tweet Önerileri", args.generate))

    elif args.quote:
        if not args.author:
            print("❌ --author gerekli. Örnek: --author elonmusk")
            sys.exit(1)
        result = generate_quote(args.quote, args.author, args.format, min(args.count, 5))
        if result:
            print(format_console(result, "Quote")) if not args.json else print(json.dumps(result, indent=2, ensure_ascii=False))
            if args.telegram:
                send_telegram(format_telegram(result, "Quote Önerileri", f"@{args.author}"))

    elif args.reply:
        if not args.author:
            print("❌ --author gerekli. Örnek: --author levelsio")
            sys.exit(1)
        result = generate_reply(args.reply, args.author, args.reply_tone, min(args.count, 5))
        if result:
            print(format_console(result, "Reply")) if not args.json else print(json.dumps(result, indent=2, ensure_ascii=False))
            if args.telegram:
                send_telegram(format_telegram(result, "Reply Önerileri", f"@{args.author}"))


if __name__ == "__main__":
    main()
