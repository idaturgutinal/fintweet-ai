#!/usr/bin/env python3
"""FinTweet Sabah Ozet - Geceki onemli gelismeleri tek tweet'te ozetler."""
from error_notifier import send_error_alert
import os
import json
import sqlite3
import requests
from datetime import datetime, timezone

# Env yukle
env_file = os.path.expanduser("~/.fintweet-env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                if line.startswith("export "):
                    line = line[7:]
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip("'").strip('"'))

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fintweet.db")
SOUL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SOUL.md")


def main():
    conn = sqlite3.connect(DB)

    # Son 12 saatin en onemli bulgulari
    highlights = conn.execute("""
        SELECT source_category, title, relevance_score FROM findings
        WHERE created_at >= datetime('now', '-12 hours') AND relevance_score > 50
        ORDER BY relevance_score DESC LIMIT 10
    """).fetchall()

    if len(highlights) < 2:
        print("[BILGI] Yeterli bulgu yok (%d), ozet atlaniyor" % len(highlights))
        conn.close()
        return

    print("[BILGI] %d onemli bulgu bulundu" % len(highlights))

    try:
        import anthropic
    except ImportError:
        print("[HATA] anthropic modulu yok")
        conn.close()
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[HATA] ANTHROPIC_API_KEY yok")
        conn.close()
        return

    soul = ""
    if os.path.exists(SOUL):
        with open(SOUL) as f:
            soul = f.read()

    topics = "\n".join("- [%s] %s (skor: %s)" % (h[0], h[1], h[2]) for h in highlights)

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=300,
        system=soul + "\n\nOZEL GOREV: Sabah ozet tweet'i yaz. Gece boyunca olan onemli gelismeleri tek tweet'te ozetle. Format: kisa ve vurucu, 2-3 madde. Max 280 karakter. Turkce yaz. Emoji max 1 tane. Hashtag ve cashtag kullanma.",
        messages=[{
            "role": "user",
            "content": "Son 12 saatin onemli gelismeleri:\n%s\n\nBunlari tek bir sabah ozet tweet'ine donustur." % topics
        }]
    )
    text = msg.content[0].text.strip().strip('"')
    if len(text) > 280:
        text = text[:277] + "..."
    print("[OZET] %s" % text)

    # DB'ye kaydet
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO telegram_suggestions (text, category, created_at, status) VALUES (?, 'morning_summary', ?, 'pending')",
        (text, now)
    )
    conn.commit()
    sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Telegram'a gonder
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if bot_token and chat_id:
        keyboard = json.dumps({"inline_keyboard": [[
            {"text": "\u2705 Onayla", "callback_data": "at_%d" % sid},
            {"text": "\u274c Reddet", "callback_data": "atma_%d" % sid},
            {"text": "\u270f\ufe0f Duzenle", "callback_data": "duzenle_%d" % sid},
        ]]})
        requests.post(
            "https://api.telegram.org/bot%s/sendMessage" % bot_token,
            json={
                "chat_id": chat_id,
                "text": "\U0001f305 <b>Sabah Ozet</b> #%d\n\n%s\n\n<i>morning_summary</i>" % (sid, text),
                "parse_mode": "HTML",
                "reply_markup": keyboard,
                "disable_web_page_preview": True,
            }
        )
        print("[OK] Sabah ozet Telegram'a gonderildi (#%d)" % sid)

    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_error_alert("morning_summary", str(e))
        raise
