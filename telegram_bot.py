#!/usr/bin/env python3
"""
FinTweet Telegram Bot - Inline buton handler + komut menusu.
Polling ile calisir, Gateway'den bagimsiz.
"""
import os, sys, json, time, sqlite3, subprocess, requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(WORKSPACE, "fintweet.db")

# Duzenleme bekleyen kullanicilar: {chat_id: suggestion_id}
pending_edits = {}


def get_updates(offset=None):
    """Telegram'dan yeni mesajlari al (long polling)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 30, "allowed_updates": json.dumps(["callback_query", "message"])}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=35)
        return r.json().get("result", [])
    except Exception:
        return []


def answer_callback(callback_query_id, text="Islendi"):
    """Callback query'yi yanitla (loading spinner kaldir)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    requests.post(url, json={"callback_query_id": callback_query_id, "text": text})


def edit_message_buttons(chat_id, message_id, reply_markup=None):
    """Mesajdaki butonlari guncelle veya kaldir."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup"
    payload = {"chat_id": chat_id, "message_id": message_id}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload)
    except Exception:
        pass


def send_message(chat_id, text, reply_markup=None):
    """Mesaj gonder."""
    if len(text) > 4000:
        text = text[:4000] + "\n... (kesildi)"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


def run_command(cmd_text):
    """telegram_commands.py'yi calistir ve ciktiyi al."""
    try:
        result = subprocess.run(
            ["python3", "telegram_commands.py", cmd_text],
            capture_output=True, text=True, timeout=60,
            cwd=WORKSPACE,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output.strip()
    except Exception as e:
        return f"Hata: {e}"


def handle_callback(update):
    """Inline buton callback'lerini isle."""
    cb = update["callback_query"]
    cb_id = cb["id"]
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    data = cb.get("data", "")

    if data.startswith("at_"):
        sid = data.split("_", 1)[1]
        answer_callback(cb_id, "Tweet atiliyor...")
        edit_message_buttons(chat_id, message_id)
        run_command(f"at {sid}")

    elif data.startswith("atma_"):
        sid = data.split("_", 1)[1]
        answer_callback(cb_id, "Reddedildi")
        edit_message_buttons(chat_id, message_id)
        run_command(f"atma {sid}")

    elif data.startswith("duzenle_"):
        sid = data.split("_", 1)[1]
        answer_callback(cb_id, "Duzenleme modu")
        edit_message_buttons(chat_id, message_id)
        pending_edits[str(chat_id)] = sid
        # Mevcut metni goster
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute("SELECT text FROM telegram_suggestions WHERE id=?", (sid,)).fetchone()
            conn.close()
            current_text = row[0] if row else "(bulunamadi)"
        except Exception:
            current_text = "(okunamadi)"
        send_message(chat_id,
            f"\u270f\ufe0f <b>Oneri #{sid} duzenleniyor</b>\n\n"
            f"Mevcut metin:\n<i>{current_text}</i>\n\n"
            f"Yeni metni yazin veya /iptal yazin:")

    elif data.startswith("quote_"):
        sid = data.split("_", 1)[1]
        answer_callback(cb_id, "Quote modu")
        edit_message_buttons(chat_id, message_id)
        # Oneriyi ve kaynak tweet'i al
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute("SELECT text, source_url FROM telegram_suggestions WHERE id=?", (sid,)).fetchone()
            conn.close()
            if row and row[1]:
                current_text = row[0] if row else "(bulunamadi)"
                source_url = row[1]
                pending_edits[str(chat_id)] = f"QUOTE:{sid}"
                send_message(chat_id,
                    f"\U0001f4ac <b>Quote Tweet #{sid}</b>\n\n"
                    f"Kaynak: {source_url}\n\n"
                    f"Onerilen metin:\n<i>{current_text}</i>\n\n"
                    f"Bu metinle quote atmak icin <b>evet</b> yazin,\n"
                    f"Farkli metin icin yeni metni yazin,\n"
                    f"Iptal icin /iptal yazin:")
            else:
                send_message(chat_id, "\u274c Bu oneri icin kaynak tweet bulunamadi.")
        except Exception:
            send_message(chat_id, "\u274c Quote bilgisi okunamadi.")


def handle_message(update):
    """Normal metin mesajlarini isle."""
    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not text or not chat_id:
        return

    # Duzenleme/Quote bekliyor mu?
    if str(chat_id) in pending_edits:
        pending_val = pending_edits.pop(str(chat_id))
        if text.lower() in ("/iptal", "iptal", "vazgec"):
            send_message(chat_id, "Iptal edildi.")
            return
        if pending_val.startswith("QUOTE:"):
            sid = pending_val.split(":", 1)[1]
            if text.lower() in ("evet", "ok", "tamam"):
                # Onerinin kendi metnini kullan
                run_command(f"quote {sid}")
            else:
                # Kullanicinin yazdigi metinle quote at
                run_command(f"quote {sid}: {text}")
            return
        # Normal duzenleme
        run_command(f"duzenle {pending_val}: {text}")
        return

    # Slash komutlari
    if text in ("/start", "/yardim", "/help"):
        send_message(chat_id,
            "<b>FinTweet Bot</b>\n\n"
            "Oneriler otomatik gelir (gunde 8 kez)\n"
            "Butonlara basarak onayla / reddet / duzenle\n\n"
            "<b>Komutlar:</b>\n"
            "/durum - Sistem durumu\n"
            "/kredi - XPatla kredi bakiyesi\n"
            "/son - Son 5 oneri\n"
            "/tara - Yeni haber tara\n"
            "/uret - Tweet uret (auto_xpatla)\n"
            "/yardim - Bu mesaj\n\n"
            "<b>Elle tweet:</b>\n"
            "<code>tweet: buraya metni yaz</code>\n\n"
            "<b>Oneri islemleri:</b>\n"
            "<code>at 7</code> - Oneriyi tweetle\n"
            "<code>atma 7</code> - Reddet\n"
            "<code>duzenle 7: yeni metin</code>\n"
            "<code>quote 7: yorum</code>\n"
            "<code>reply 7: cevap</code>")
        return

    if text == "/durum":
        run_command("durum")
        return

    if text == "/kredi":
        run_command("kredi")
        return

    if text == "/son":
        run_command("son")
        return

    if text == "/tara":
        send_message(chat_id, "Tarama baslatiliyor...")
        try:
            result = subprocess.run(
                ["python3", "scanner.py"],
                capture_output=True, text=True, timeout=120,
                cwd=WORKSPACE,
                env={**os.environ},
            )
            lines = (result.stdout or "").strip().split("\n")
            # Son 5 satiri goster (sonuc ozeti)
            summary = "\n".join(lines[-5:]) if len(lines) > 5 else "\n".join(lines)
            send_message(chat_id, f"Tarama tamamlandi:\n<pre>{summary}</pre>")
        except subprocess.TimeoutExpired:
            send_message(chat_id, "Tarama zaman asimina ugradi (2dk)")
        except Exception as e:
            send_message(chat_id, f"Tarama hatasi: {e}")
        return

    if text == "/uret":
        send_message(chat_id, "Tweet uretimi baslatiliyor...")
        try:
            result = subprocess.run(
                ["python3", "auto_xpatla.py"],
                capture_output=True, text=True, timeout=180,
                cwd=WORKSPACE,
                env={**os.environ},
            )
            lines = (result.stdout or "").strip().split("\n")
            summary = "\n".join(lines[-5:]) if len(lines) > 5 else "\n".join(lines)
            send_message(chat_id, f"Uretim tamamlandi:\n<pre>{summary}</pre>")
        except subprocess.TimeoutExpired:
            send_message(chat_id, "Tweet uretimi zaman asimina ugradi (3dk)")
        except Exception as e:
            send_message(chat_id, f"Uretim hatasi: {e}")
        return

    # Bare text komutlari: at 7, atma 3, tweet: metin, quote, reply vb.
    # telegram_commands.py'ye yonlendir
    import re
    if re.match(r'^(at\s|atma\s|at$|atma$|duzenle\s|quote\s|reply\s|tweet\s*:|kredi$|durum$|son$|liste$|\d+$)', text, re.IGNORECASE):
        run_command(text)
        return


def setup_bot_commands():
    """Telegram menu komutlarini ayarla (/ yazinca gorunsun)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "durum", "description": "Sistem durumu"},
        {"command": "kredi", "description": "XPatla kredi bakiyesi"},
        {"command": "son", "description": "Son 5 oneri"},
        {"command": "tara", "description": "Yeni haber tara"},
        {"command": "uret", "description": "Tweet uret (auto_xpatla)"},
        {"command": "yardim", "description": "Yardim ve komutlar"},
    ]
    requests.post(url, json={"commands": commands})


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[HATA] TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik")
        sys.exit(1)

    print(f"[BASLA] telegram_bot.py - Inline buton handler (PID: {os.getpid()})")
    setup_bot_commands()
    print("[BILGI] Bot komutlari ayarlandi")

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    handle_callback(update)
                elif "message" in update:
                    handle_message(update)
        except KeyboardInterrupt:
            print("\n[DURDUR] telegram_bot.py kapatiliyor")
            break
        except Exception as e:
            print(f"[HATA] {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
