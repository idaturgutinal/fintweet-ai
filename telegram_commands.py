#!/usr/bin/env python3
"""
FinTweet AI - Telegram Komut Isleyici (telegram_commands.py)
=============================================================
Telegram'dan gelen komutlari isler, tweet atar, oneri yonetir.

Kullanim:
  python3 telegram_commands.py "at 7"
  python3 telegram_commands.py "atma 3"
  python3 telegram_commands.py "duzenle 7: yeni metin"
  python3 telegram_commands.py "quote 7: yorum"
  python3 telegram_commands.py "reply 7: cevap"
  python3 telegram_commands.py "kredi"
  python3 telegram_commands.py "durum"
  python3 telegram_commands.py "son"
  python3 telegram_commands.py "tweet: metin buraya"
"""

import os
import sys
import re
import json
import sqlite3
import subprocess
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

WORKSPACE = Path.home() / ".openclaw" / "workspace"
DB_PATH = WORKSPACE / "fintweet.db"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_suggestions_table(conn):
    """telegram_suggestions tablosunu olustur (yoksa)."""
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


def send_telegram(message, parse_mode="HTML", reply_markup=None):
    """Telegram'a mesaj gonder, opsiyonel inline keyboard ile."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
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


def get_suggestion(conn, number=None):
    """Oneri getir. number=None ise son pending oneriyi getir."""
    if number:
        row = conn.execute(
            "SELECT * FROM telegram_suggestions WHERE id = ?", (number,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM telegram_suggestions WHERE status = 'pending' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def extract_tweet_id_from_url(url):
    """URL'den tweet ID cikar."""
    if not url:
        return None
    match = re.search(r'/status/(\d+)', url)
    return match.group(1) if match else None


def run_tweet_py(args_list):
    """tweet.py'yi calistir, sonucu dondur."""
    cmd = ["python3", str(WORKSPACE / "tweet.py")] + args_list
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
        cwd=str(WORKSPACE), env={**os.environ}
    )
    return result


def extract_tweet_url(output):
    """tweet.py ciktisinden tweet URL'sini cikar."""
    match = re.search(r'https://(?:twitter\.com|x\.com)/\S+/status/\d+', output)
    return match.group(0) if match else None


def tweet_succeeded(result):
    """tweet.py basarili mi? returncode yetersiz, stdout'ta URL kontrolu yap."""
    if result.returncode != 0:
        return False
    out = result.stdout or ""
    return "Tweet posted!" in out or "Tweet posted (fallback)!" in out


def tweet_used_fallback(result):
    """tweet.py fallback kullanmis mi?"""
    return "fallback" in (result.stdout or "").lower()


def tweet_error_message(result):
    """tweet.py hata mesajini cikar."""
    output = (result.stdout or "") + (result.stderr or "")
    # "Error NNN:" satirini bul
    match = re.search(r'Error \d+:.*', output)
    if match:
        return match.group(0)[:200]
    return output.strip()[:200] or "Bilinmeyen hata"


# === KOMUT ISLEYICILERI ===

def cmd_at(conn, number=None):
    """Tweet at."""
    suggestion = get_suggestion(conn, number)
    if not suggestion:
        num_str = f"#{number}" if number else "son"
        send_telegram(f"\u274c {num_str} numarali oneri bulunamadi veya zaten islenmis.")
        return

    text = suggestion["text"]
    try:
        result = run_tweet_py([text])
        if tweet_succeeded(result):
            tweet_url = extract_tweet_url(result.stdout) or ""
            conn.execute("UPDATE telegram_suggestions SET status = 'sent' WHERE id = ?",
                         (suggestion["id"],))
            conn.commit()

            short = text[:80] + "..." if len(text) > 80 else text
            msg = f"\u2705 Tweet atildi!\n<code>{short}</code>"
            if tweet_url:
                msg += f"\n\U0001f517 {tweet_url}"
            send_telegram(msg)
        else:
            send_telegram(f"\u274c Tweet atilamadi: {tweet_error_message(result)}")
    except subprocess.TimeoutExpired:
        send_telegram("\u274c Tweet atma zaman asimina ugradi.")
    except Exception as e:
        send_telegram(f"\u274c Hata: {e}")


def cmd_atma(conn, number=None):
    """Oneriyi reddet."""
    suggestion = get_suggestion(conn, number)
    if not suggestion:
        num_str = f"#{number}" if number else "son"
        send_telegram(f"\u274c {num_str} numarali oneri bulunamadi.")
        return

    conn.execute("UPDATE telegram_suggestions SET status = 'rejected' WHERE id = ?",
                 (suggestion["id"],))
    conn.commit()

    short = suggestion["text"][:60] + "..." if len(suggestion["text"]) > 60 else suggestion["text"]
    send_telegram(f"\U0001f6ab Oneri #{suggestion['id']} reddedildi.\n<i>{short}</i>")


def cmd_duzenle(conn, number, new_text):
    """Oneriyi duzenle ve at."""
    if not new_text.strip():
        send_telegram("\u274c Duzenleme metni bos olamaz.")
        return

    suggestion = get_suggestion(conn, number)

    try:
        result = run_tweet_py([new_text.strip()])
        if tweet_succeeded(result):
            tweet_url = extract_tweet_url(result.stdout) or ""
            if suggestion:
                conn.execute("UPDATE telegram_suggestions SET status = 'edited' WHERE id = ?",
                             (suggestion["id"],))
                conn.commit()

            short = new_text[:80] + "..." if len(new_text) > 80 else new_text
            msg = f"\u2705 Duzenlenmis tweet atildi!\n<code>{short}</code>"
            if tweet_url:
                msg += f"\n\U0001f517 {tweet_url}"
            send_telegram(msg)
        else:
            send_telegram(f"\u274c Tweet atilamadi: {tweet_error_message(result)}")
    except Exception as e:
        send_telegram(f"\u274c Hata: {e}")


def cmd_quote(conn, number, comment=None, manual_url=None):
    """Quote tweet at. comment=None ise onerinin kendi metnini kullan."""
    suggestion = None
    tweet_url = manual_url

    if not tweet_url and number:
        suggestion = get_suggestion(conn, number)
        if suggestion:
            tweet_url = suggestion.get("source_url", "")

    if not tweet_url:
        send_telegram("\u274c Quote tweet icin kaynak URL bulunamadi.")
        return

    tweet_id = extract_tweet_id_from_url(tweet_url)
    if not tweet_id:
        send_telegram(f"\u274c URL'den tweet ID cikarilamadi: {tweet_url}")
        return

    # Yorum belirtilmemisse onerinin kendi metnini kullan
    if not comment and suggestion:
        comment = suggestion["text"]
    elif not comment:
        send_telegram("\u274c Quote icin metin bulunamadi.")
        return

    try:
        result = run_tweet_py([comment.strip(), "--quote", tweet_id])
        if tweet_succeeded(result):
            result_url = extract_tweet_url(result.stdout) or ""
            if suggestion:
                conn.execute("UPDATE telegram_suggestions SET status = 'sent' WHERE id = ?",
                             (suggestion["id"],))
                conn.commit()

            short = comment[:80] + "..." if len(comment) > 80 else comment
            if tweet_used_fallback(result):
                msg = f"\u26a0\ufe0f Quote kisitli, link ile atildi!\n<code>{short}</code>"
            else:
                msg = f"\u2705 Quote tweet atildi!\n<code>{short}</code>"
            if result_url:
                msg += f"\n\U0001f517 {result_url}"
            send_telegram(msg)
        else:
            send_telegram(f"\u274c Quote tweet atilamadi: {tweet_error_message(result)}")
    except Exception as e:
        send_telegram(f"\u274c Hata: {e}")


def cmd_reply(conn, number, reply_text):
    """Reply at."""
    suggestion = get_suggestion(conn, number) if number else None
    tweet_url = suggestion.get("source_url", "") if suggestion else ""

    if not tweet_url:
        send_telegram("\u274c Reply icin kaynak tweet URL bulunamadi.")
        return

    tweet_id = extract_tweet_id_from_url(tweet_url)
    if not tweet_id:
        send_telegram(f"\u274c URL'den tweet ID cikarilamadi: {tweet_url}")
        return

    try:
        result = run_tweet_py([reply_text.strip(), "--reply-to", tweet_id])
        if tweet_succeeded(result):
            result_url = extract_tweet_url(result.stdout) or ""
            msg = f"\u2705 Reply atildi!\n<code>{reply_text[:80]}</code>"
            if result_url:
                msg += f"\n\U0001f517 {result_url}"
            send_telegram(msg)
        else:
            send_telegram(f"\u274c Reply atilamadi: {tweet_error_message(result)}")
    except Exception as e:
        send_telegram(f"\u274c Hata: {e}")


def get_xpatla_credits():
    """XPatla API'den kredi bilgisini al ve parse et."""
    try:
        result = subprocess.run(
            ["python3", str(WORKSPACE / "xpatla.py"), "--credits"],
            capture_output=True, text=True, timeout=15,
            cwd=str(WORKSPACE), env={**os.environ}
        )
        output = (result.stdout or result.stderr).strip()
        # JSON'u parse et
        import json as _json
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                # Onceki satirlarla birlestir
                json_str = output[output.index("{"):]
                data = _json.loads(json_str)
                if data.get("success") and "data" in data:
                    d = data["data"]
                    return {
                        "balance": d.get("credits_balance", 0),
                        "monthly": d.get("monthly_credits", 0),
                        "tier": d.get("tier", "?"),
                        "reset_at": d.get("credits_reset_at", ""),
                    }
                break
    except Exception:
        pass
    return None


def cmd_kredi():
    """XPatla kredi bakiyesi."""
    credits = get_xpatla_credits()
    if credits:
        # Reset tarihini formatla
        reset_str = credits["reset_at"][:10] if credits["reset_at"] else "?"
        if reset_str and reset_str != "?":
            try:
                from datetime import datetime as _dt
                rd = _dt.strptime(reset_str, "%Y-%m-%d")
                aylar = ["Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
                         "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik"]
                reset_str = f"{rd.day} {aylar[rd.month - 1]} {rd.year}"
            except Exception:
                pass
        tier = credits["tier"].capitalize()
        send_telegram(
            f"\U0001f4b0 XPatla Kredi: <b>{credits['balance']}/{credits['monthly']}</b>"
            f" | Tier: {tier} | Reset: {reset_str}"
        )
    else:
        send_telegram("\u274c Kredi bilgisi alinamadi.")


def cmd_durum(conn):
    """Sistem durumu."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Son tarama
    last_scan = conn.execute(
        "SELECT created_at FROM findings ORDER BY created_at DESC LIMIT 1"
    ).fetchone()

    # Bugun atilan tweetler
    tweets_today = conn.execute(
        "SELECT COUNT(*) FROM telegram_suggestions WHERE status = 'sent' AND created_at >= ?",
        (today,)
    ).fetchone()[0]

    # Bekleyen oneriler
    pending = conn.execute(
        "SELECT COUNT(*) FROM telegram_suggestions WHERE status = 'pending'"
    ).fetchone()[0]

    # XPatla cagrilari bugun
    xpatla_today = conn.execute(
        "SELECT COUNT(DISTINCT topic) FROM xpatla_generations WHERE created_at >= ?",
        (today + "T00:00:00",)
    ).fetchone()[0]

    # Canli kredi (XPatla API'den)
    credits = get_xpatla_credits()
    if credits:
        kredi_str = f"{credits['balance']}/{credits['monthly']}"
    else:
        # Fallback: DB'den son bilinen deger
        credits_row = conn.execute(
            "SELECT remaining_credits FROM xpatla_generations ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        kredi_str = str(credits_row[0]) if credits_row and credits_row[0] else "?"

    last_time = last_scan[0][:16] if last_scan else "?"

    msg = (
        f"\U0001f4ca <b>Sistem Durumu</b>\n\n"
        f"\U0001f50d Son tarama: {last_time}\n"
        f"\U0001f4b0 Kredi: {kredi_str}\n"
        f"\U0001f916 XPatla bugun: {xpatla_today}/8\n"
        f"\U0001f426 Tweet bugun: {tweets_today}\n"
        f"\U0001f4dd Bekleyen oneri: {pending}\n"
    )
    send_telegram(msg)


def cmd_son(conn):
    """Son 5 oneriyi listele."""
    rows = conn.execute(
        "SELECT id, text, category, status, created_at FROM telegram_suggestions ORDER BY id DESC LIMIT 5"
    ).fetchall()

    if not rows:
        send_telegram("\U0001f4ed Henuz oneri yok.")
        return

    lines = ["\U0001f4cb <b>Son 5 Oneri</b>\n"]
    status_icons = {"pending": "\u23f3", "sent": "\u2705", "rejected": "\U0001f6ab", "edited": "\u270f\ufe0f"}
    for r in rows:
        icon = status_icons.get(r["status"], "\u2753")
        short = r["text"][:60] + "..." if len(r["text"]) > 60 else r["text"]
        lines.append(f"{icon} <b>#{r['id']}</b> [{r['category'] or '?'}]")
        lines.append(f"<code>{short}</code>\n")

    send_telegram("\n".join(lines))


def cmd_tweet(text, media=None):
    """Direkt tweet at (oneri sisteminden bagimsiz)."""
    args = [text.strip()]
    if media:
        args.extend(["--media", media])

    try:
        result = run_tweet_py(args)
        if tweet_succeeded(result):
            tweet_url = extract_tweet_url(result.stdout) or ""
            short = text[:80] + "..." if len(text) > 80 else text
            msg = f"\u2705 Tweet atildi!\n<code>{short}</code>"
            if tweet_url:
                msg += f"\n\U0001f517 {tweet_url}"
            send_telegram(msg)
        else:
            send_telegram(f"\u274c Tweet atilamadi: {tweet_error_message(result)}")
    except Exception as e:
        send_telegram(f"\u274c Hata: {e}")


# === KOMUT PARSER ===

def parse_and_execute(command_str):
    """Komutu parse et ve calistir."""
    conn = get_db()
    init_suggestions_table(conn)

    cmd = command_str.strip()

    # "at 7"
    m = re.match(r'^at\s+(\d+)$', cmd)
    if m:
        cmd_at(conn, int(m.group(1)))
        conn.close()
        return

    # "at"
    if cmd == 'at':
        cmd_at(conn)
        conn.close()
        return

    # Sadece rakam: "7" → at, "0" → atma
    m = re.match(r'^(\d+)$', cmd)
    if m:
        num = int(m.group(1))
        if num == 0:
            cmd_atma(conn)
        else:
            cmd_at(conn, num)
        conn.close()
        return

    # "atma 7"
    m = re.match(r'^atma\s+(\d+)$', cmd)
    if m:
        cmd_atma(conn, int(m.group(1)))
        conn.close()
        return

    # "atma" veya "0"
    if cmd in ('atma', '0'):
        cmd_atma(conn)
        conn.close()
        return

    # "duzenle 7: yeni metin"
    m = re.match(r'^d[uü]zenle\s+(\d+)\s*:\s*(.+)$', cmd, re.DOTALL)
    if m:
        cmd_duzenle(conn, int(m.group(1)), m.group(2))
        conn.close()
        return

    # "duzenle: yeni metin"
    m = re.match(r'^d[uü]zenle\s*:\s*(.+)$', cmd, re.DOTALL)
    if m:
        cmd_duzenle(conn, None, m.group(1))
        conn.close()
        return

    # "quote 7: yorum"
    m = re.match(r'^quote\s+(\d+)\s*:\s*(.+)$', cmd, re.DOTALL)
    if m:
        cmd_quote(conn, int(m.group(1)), m.group(2))
        conn.close()
        return

    # "quote 7" (yorumsuz - onerinin kendi metnini kullan)
    m = re.match(r'^quote\s+(\d+)$', cmd)
    if m:
        cmd_quote(conn, int(m.group(1)))
        conn.close()
        return

    # "quote: yorum --tweet URL"
    m = re.match(r'^quote\s*:\s*(.+?)\s+--tweet\s+(\S+)\s*$', cmd, re.DOTALL)
    if m:
        cmd_quote(conn, None, m.group(1), m.group(2))
        conn.close()
        return

    # "quote: yorum" (URL'siz — son oneri kullanilir)
    m = re.match(r'^quote\s*:\s*(.+)$', cmd, re.DOTALL)
    if m:
        cmd_quote(conn, None, m.group(1))
        conn.close()
        return

    # "reply 7: cevap"
    m = re.match(r'^reply\s+(\d+)\s*:\s*(.+)$', cmd, re.DOTALL)
    if m:
        cmd_reply(conn, int(m.group(1)), m.group(2))
        conn.close()
        return

    # "kredi"
    if cmd == 'kredi':
        cmd_kredi()
        conn.close()
        return

    # "durum"
    if cmd == 'durum':
        cmd_durum(conn)
        conn.close()
        return

    # "son" veya "liste"
    if cmd in ('son', 'liste'):
        cmd_son(conn)
        conn.close()
        return

    # "tweet: metin --media dosya"
    m = re.match(r'^tweet\s*:\s*(.+?)\s+--media\s+(\S+)\s*$', cmd, re.DOTALL)
    if m:
        cmd_tweet(m.group(1), m.group(2))
        conn.close()
        return

    # "tweet: metin"
    m = re.match(r'^tweet\s*:\s*(.+)$', cmd, re.DOTALL)
    if m:
        cmd_tweet(m.group(1))
        conn.close()
        return

    # Bilinmeyen komut
    send_telegram(
        f"\u2753 Bilinmeyen komut: <code>{cmd[:50]}</code>\n\n"
        "<b>Komutlar:</b>\n"
        "<code>at 7</code> \u2014 tweeti at\n"
        "<code>atma 7</code> \u2014 reddet\n"
        "<code>d\u00fczlenle 7: metin</code> \u2014 d\u00fczenle ve at\n"
        "<code>quote 7: yorum</code> \u2014 quote tweet\n"
        "<code>reply 7: cevap</code> \u2014 reply\n"
        "<code>kredi</code> \u2014 XPatla bakiye\n"
        "<code>durum</code> \u2014 sistem durumu\n"
        "<code>son</code> \u2014 son 5 \u00f6neri\n"
        "<code>tweet: metin</code> \u2014 direkt tweet"
    )
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Kullanim: python3 telegram_commands.py \"komut\"")
        print("Ornek:    python3 telegram_commands.py \"at 7\"")
        sys.exit(1)

    command = " ".join(sys.argv[1:])
    parse_and_execute(command)
