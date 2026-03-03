#!/usr/bin/env python3
"""FinTweet Engagement Tracker - Tweet performansini takip eder."""
from error_notifier import send_error_alert
import os
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
BEARER = os.environ.get("TWITTER_BEARER_TOKEN", "")


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS tweet_engagement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tweet_id TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        likes INTEGER DEFAULT 0,
        retweets INTEGER DEFAULT 0,
        replies INTEGER DEFAULT 0,
        impressions INTEGER DEFAULT 0,
        bookmarks INTEGER DEFAULT 0,
        quote_tweets INTEGER DEFAULT 0
    )""")
    # tweets tablosuna engagement kolonlari ekle
    for col in ["likes INTEGER DEFAULT 0", "retweets INTEGER DEFAULT 0",
                "replies INTEGER DEFAULT 0", "impressions INTEGER DEFAULT 0",
                "engagement_score REAL DEFAULT 0"]:
        try:
            conn.execute("ALTER TABLE tweets ADD COLUMN %s" % col)
        except Exception:
            pass
    conn.commit()


def fetch_metrics(tweet_ids):
    """Twitter API v2 ile tweet metriklerini al."""
    if not BEARER or not tweet_ids:
        return {}
    headers = {"Authorization": "Bearer %s" % BEARER}
    ids_str = ",".join(tweet_ids[:100])
    try:
        r = requests.get(
            "https://api.twitter.com/2/tweets?ids=%s&tweet.fields=public_metrics" % ids_str,
            headers=headers, timeout=15
        )
        if r.status_code == 200:
            result = {}
            for t in r.json().get("data", []):
                m = t.get("public_metrics", {})
                result[t["id"]] = {
                    "likes": m.get("like_count", 0),
                    "retweets": m.get("retweet_count", 0),
                    "replies": m.get("reply_count", 0),
                    "impressions": m.get("impression_count", 0),
                    "bookmarks": m.get("bookmark_count", 0),
                    "quote_tweets": m.get("quote_count", 0),
                }
            return result
        else:
            print("[HATA] Twitter API %d: %s" % (r.status_code, r.text[:200]))
    except Exception as e:
        print("[HATA] %s" % e)
    return {}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)

    # Son 48 saatteki tweetleri al
    rows = conn.execute(
        "SELECT id FROM tweets WHERE id IS NOT NULL AND created_at >= datetime('now', '-48 hours')"
    ).fetchall()
    tweet_ids = [r["id"] for r in rows if r["id"]]

    if not tweet_ids:
        print("[BILGI] Takip edilecek tweet yok")
        conn.close()
        return

    print("[BILGI] %d tweet kontrol ediliyor..." % len(tweet_ids))
    metrics = fetch_metrics(tweet_ids)

    now = datetime.now(timezone.utc).isoformat()
    for tid, m in metrics.items():
        conn.execute(
            "INSERT INTO tweet_engagement (tweet_id,checked_at,likes,retweets,replies,impressions,bookmarks,quote_tweets) VALUES (?,?,?,?,?,?,?,?)",
            (tid, now, m["likes"], m["retweets"], m["replies"], m["impressions"], m["bookmarks"], m["quote_tweets"])
        )
        eng = m["likes"] + m["retweets"] * 2 + m["replies"] * 3 + m["bookmarks"] * 1.5
        conn.execute(
            "UPDATE tweets SET likes=?,retweets=?,replies=?,impressions=?,engagement_score=? WHERE id=?",
            (m["likes"], m["retweets"], m["replies"], m["impressions"], eng, tid)
        )
        print("  %s: %dL %dRT %dR imp=%d score=%.0f" % (
            tid, m["likes"], m["retweets"], m["replies"], m["impressions"], eng))

    conn.commit()
    conn.close()
    print("[OK] %d tweet guncellendi" % len(metrics))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_error_alert("engagement_tracker", str(e))
        raise
