#!/usr/bin/env python3
"""FinTweet Haftalik Performans Raporu"""
from error_notifier import send_error_alert
import os
import sqlite3
import requests
from datetime import datetime

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


def main():
    conn = sqlite3.connect(DB)
    s = {}
    s["findings"] = conn.execute("SELECT COUNT(*) FROM findings WHERE created_at >= datetime('now', '-7 days')").fetchone()[0]
    s["web"] = conn.execute("SELECT COUNT(*) FROM findings WHERE source_type='web' AND created_at >= datetime('now', '-7 days')").fetchone()[0]
    s["twitter"] = conn.execute("SELECT COUNT(*) FROM findings WHERE source_type='twitter' AND created_at >= datetime('now', '-7 days')").fetchone()[0]
    s["suggestions"] = conn.execute("SELECT COUNT(*) FROM telegram_suggestions WHERE created_at >= datetime('now', '-7 days')").fetchone()[0]
    s["sent"] = conn.execute("SELECT COUNT(*) FROM telegram_suggestions WHERE status='sent' AND created_at >= datetime('now', '-7 days')").fetchone()[0]
    s["pending"] = conn.execute("SELECT COUNT(*) FROM telegram_suggestions WHERE status='pending' AND created_at >= datetime('now', '-7 days')").fetchone()[0]

    top_cats = conn.execute(
        "SELECT source_category, COUNT(*) as cnt FROM findings WHERE created_at >= datetime('now', '-7 days') GROUP BY source_category ORDER BY cnt DESC LIMIT 5"
    ).fetchall()

    # Engagement verileri (varsa)
    try:
        top_tweets = conn.execute(
            "SELECT text, engagement_score, likes, retweets FROM tweets WHERE created_at >= datetime('now', '-7 days') AND engagement_score > 0 ORDER BY engagement_score DESC LIMIT 3"
        ).fetchall()
    except Exception:
        top_tweets = []

    # Rapor olustur
    report = "\U0001f4ca <b>Haftalik Rapor</b> (%s)\n\n" % datetime.now().strftime("%d.%m.%Y")
    report += "\U0001f50d <b>Tarama</b>\nBulgu: %d (web: %d, twitter: %d)\n\n" % (s["findings"], s["web"], s["twitter"])
    report += "\U0001f4dd <b>Tweet</b>\nOneri: %d | Atilan: %d | Bekleyen: %d\n\n" % (s["suggestions"], s["sent"], s["pending"])

    report += "\U0001f3c6 <b>En Aktif Kategoriler</b>"
    for cat, cnt in top_cats:
        report += "\n  %s: %d" % (cat, cnt)

    if top_tweets:
        report += "\n\n\u2b50 <b>En Iyi Tweetler</b>"
        for t in top_tweets:
            report += "\n  %dL %dRT: %s" % (t[2], t[3], t[0][:50])

    if s["suggestions"] > 0:
        approval_rate = s["sent"] / s["suggestions"] * 100
        report += "\n\n\U0001f4c8 Onay orani: %%%d" % approval_rate

    # Telegram'a gonder
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if bot_token and chat_id:
        requests.post(
            "https://api.telegram.org/bot%s/sendMessage" % bot_token,
            json={
                "chat_id": chat_id,
                "text": report,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        )
        print("[OK] Haftalik rapor Telegram'a gonderildi")
    else:
        print(report)

    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_error_alert("weekly_report", str(e))
        raise
