#!/usr/bin/env python3
"""
FinTweet AI - Tweet Atma (Media + Quote Tweet Destekli)

Kullanim:
  python3 tweet.py "tweet metni"
  python3 tweet.py "tweet metni" --media resim.png
  python3 tweet.py "tweet metni" --quote TWEET_ID
  python3 tweet.py "tweet metni" --quote https://x.com/user/status/123456
  python3 tweet.py "tweet metni" --media grafik.png --quote TWEET_ID
"""

import sys
import os
import re
import json
import argparse
import sqlite3
from datetime import datetime, timezone, timezone
from requests_oauthlib import OAuth1Session

DB_PATH = os.path.expanduser("~/.openclaw/workspace/fintweet.db")

def get_oauth():
    return OAuth1Session(
        os.environ['TWITTER_API_KEY'],
        client_secret=os.environ['TWITTER_API_SECRET'],
        resource_owner_key=os.environ['TWITTER_ACCESS_TOKEN'],
        resource_owner_secret=os.environ['TWITTER_ACCESS_TOKEN_SECRET']
    )

def extract_tweet_id(input_str):
    """Tweet ID veya URL'den ID cikart."""
    if not input_str:
        return None
    # Eger sadece rakamsa direkt ID
    if input_str.strip().isdigit():
        return input_str.strip()
    # URL'den cikart: https://x.com/user/status/123456 veya https://twitter.com/user/status/123456
    match = re.search(r'(?:x\.com|twitter\.com)/\w+/status/(\d+)', input_str)
    if match:
        return match.group(1)
    return None

def upload_media(oauth, filepath, alt_text=None):
    """Resmi Twitter'a yukle, media_id dondur."""
    if not os.path.exists(filepath):
        print(f"HATA: Dosya bulunamadi: {filepath}")
        return None
    
    size = os.path.getsize(filepath)
    if size > 5 * 1024 * 1024:
        print(f"HATA: Dosya cok buyuk ({size // 1024}KB). Limit: 5MB")
        return None
    
    ext = os.path.splitext(filepath)[1].lower()
    mime_types = {
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.webp': 'image/webp',
    }
    mime = mime_types.get(ext, 'image/png')
    
    upload_url = "https://upload.twitter.com/1.1/media/upload.json"
    with open(filepath, 'rb') as f:
        files = {"media": (os.path.basename(filepath), f, mime)}
        resp = oauth.post(upload_url, files=files)
    
    if resp.status_code == 200:
        media_id = resp.json()['media_id_string']
        if alt_text:
            alt_url = "https://upload.twitter.com/1.1/media/metadata/create.json"
            oauth.post(alt_url, json={"media_id": media_id, "alt_text": {"text": alt_text[:1000]}})
        return media_id
    else:
        print(f"Media upload hatasi {resp.status_code}: {resp.text[:200]}")
        return None

def post_tweet(text, media_path=None, alt_text=None, reply_to=None, quote_tweet_id=None):
    """Tweet at — media, reply, quote tweet destekli."""
    oauth = get_oauth()
    
    payload = {"text": text}
    
    # Media
    if media_path:
        media_id = upload_media(oauth, media_path, alt_text)
        if media_id:
            payload["media"] = {"media_ids": [media_id]}
            print(f"  Media yuklendi: {os.path.basename(media_path)}")
        else:
            print("  UYARI: Media yuklenemedi, tweeti mediasiz atiyorum...")
    
    # Reply
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    
    # Quote Tweet
    if quote_tweet_id:
        payload["quote_tweet_id"] = str(quote_tweet_id)
        print(f"  Quote tweet: {quote_tweet_id}")
    
    fallback_used = False
    resp = oauth.post('https://api.x.com/2/tweets', json=payload)
    data = resp.json()
    
    # 403 fallback: quote kisitliysa normal tweet + link olarak at
    if resp.status_code == 403 and quote_tweet_id:
        err_msg = str(data).lower()
        if "quote" in err_msg or "not allowed" in err_msg or "forbidden" in err_msg:
            print(f"  [FALLBACK] Quote kisitli (403), link ile atiliyor...")
            link = f"https://x.com/i/status/{quote_tweet_id}"
            fallback_text = f"{text}\n\n{link}" if link not in text else text
            if len(fallback_text) > 280:
                fallback_text = f"{text[:250]}...\n\n{link}"
            fallback_payload = {"text": fallback_text}
            if "media" in payload:
                fallback_payload["media"] = payload["media"]
            resp = oauth.post('https://api.x.com/2/tweets', json=fallback_payload)
            data = resp.json()
            fallback_used = True

    if resp.status_code == 201:
        tid = data['data']['id']
        url = f"https://x.com/equinoxistr/status/{tid}"
        if fallback_used:
            print(f"Tweet posted (fallback)! {url}")
        else:
            print(f"Tweet posted! {url}")
        
        save_to_db(tid, text, media_path, quote_tweet_id)
        return {"id": tid, "url": url, "fallback": fallback_used}
    else:
        print(f"Error {resp.status_code}: {data}")
        return None

def save_to_db(tweet_id, text, media_path=None, quote_id=None):
    """Tweet'i veritabanina kaydet."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            text TEXT,
            type TEXT,
            source TEXT,
            thread_id TEXT,
            thread_position INTEGER,
            created_at TEXT
        )""")
        
        source = "tweet.py"
        if media_path:
            source += f" [media:{os.path.basename(media_path)}]"
        if quote_id:
            source += f" [quote:{quote_id}]"
        
        now = datetime.now(timezone.utc).isoformat()
        c.execute("""INSERT OR REPLACE INTO tweets (id, text, type, source, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (tweet_id, text, "unknown", source, now))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

def main():
    parser = argparse.ArgumentParser(description="FinTweet AI Tweet (Media + Quote)")
    parser.add_argument("text", nargs="?", help="Tweet metni")
    parser.add_argument("--media", "-m", help="Eklenecek resim dosyasi")
    parser.add_argument("--alt", help="Resim alt text")
    parser.add_argument("--reply-to", "-r", help="Reply yapilacak tweet ID")
    parser.add_argument("--quote", "-q", help="Alinti yapilacak tweet ID veya URL")
    
    args = parser.parse_args()
    
    if not args.text:
        if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
            text = sys.argv[1]
            post_tweet(text)
        else:
            print("Usage: python3 tweet.py \"tweet metni\" [--media resim.png] [--quote TWEET_ID]")
            sys.exit(1)
    else:
        quote_id = extract_tweet_id(args.quote) if args.quote else None
        post_tweet(args.text, media_path=args.media, alt_text=args.alt, 
                   reply_to=args.reply_to, quote_tweet_id=quote_id)

if __name__ == "__main__":
    main()
