#!/usr/bin/env python3
"""FinTweet Hata Bildirimi - Scriptlerdeki hatalari Telegram'a bildirir."""
import os
import requests


def send_error_alert(script_name, error_message):
    """Telegram'a hata bildirimi gonder."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return
    text = "\u26a0\ufe0f HATA [%s]\n%s" % (script_name, str(error_message)[:500])
    try:
        requests.post(
            "https://api.telegram.org/bot%s/sendMessage" % bot_token,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        pass
