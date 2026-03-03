#!/usr/bin/env python3
"""
FinTweet AI - Thread Atma Scripti
Birden fazla tweeti reply chain olarak atar.

Kullanim:
  python3 thread.py "Tweet 1" "Tweet 2" "Tweet 3"
  python3 thread.py --file thread.txt    (her satir bir tweet)
  python3 thread.py --json thread.json   (tweets array)
  
Otomatik (1/N) numaralama ekler (--no-number ile kapatilabilir).
"""

import sys
import os
import json
import time
import argparse
import sqlite3
from datetime import datetime
from requests_oauthlib import OAuth1Session

# ============================================================
# CONFIG
# ============================================================

DB_PATH = os.path.expanduser("~/.openclaw/workspace/fintweet.db")
TWEET_DELAY = 3  # saniye - tweetler arasi bekleme
MAX_TWEET_LEN = 280

def get_oauth():
    """OAuth1 session olustur."""
    keys = ['TWITTER_API_KEY', 'TWITTER_API_SECRET', 
            'TWITTER_ACCESS_TOKEN', 'TWITTER_ACCESS_TOKEN_SECRET']
    for k in keys:
        if not os.environ.get(k):
            print(f"HATA: {k} environment variable bulunamadi!")
            sys.exit(1)
    
    return OAuth1Session(
        os.environ['TWITTER_API_KEY'],
        client_secret=os.environ['TWITTER_API_SECRET'],
        resource_owner_key=os.environ['TWITTER_ACCESS_TOKEN'],
        resource_owner_secret=os.environ['TWITTER_ACCESS_TOKEN_SECRET']
    )

def post_tweet(oauth, text, reply_to=None):
    """Tek tweet at, opsiyonel reply."""
    payload = {"text": text}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
    
    resp = oauth.post("https://api.x.com/2/tweets", json=payload)
    data = resp.json()
    
    if resp.status_code == 201:
        tweet_id = data['data']['id']
        return tweet_id
    else:
        print(f"  HATA {resp.status_code}: {data}")
        return None

def save_thread_to_db(tweet_ids, tweets, thread_type="thread"):
    """Thread'i veritabanina kaydet."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # tweets tablosu yoksa olustur
        c.execute("""CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            text TEXT,
            type TEXT,
            source TEXT,
            thread_id TEXT,
            thread_position INTEGER,
            created_at TEXT
        )""")
        
        thread_id = tweet_ids[0] if tweet_ids else None
        now = datetime.utcnow().isoformat()
        
        for i, (tid, text) in enumerate(zip(tweet_ids, tweets)):
            if tid:
                c.execute("""INSERT OR REPLACE INTO tweets 
                    (id, text, type, source, thread_id, thread_position, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (tid, text, thread_type, "thread.py", thread_id, i+1, now))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  DB kayit hatasi: {e}")

def post_thread(tweets, add_numbers=True, dry_run=False):
    """Thread olarak tweetleri sirayla at."""
    total = len(tweets)
    
    if total < 2:
        print("HATA: Thread icin en az 2 tweet gerekli!")
        sys.exit(1)
    
    if total > 25:
        print("UYARI: 25'ten fazla tweet thread'i cok uzun olabilir!")
    
    # Numaralama ekle
    if add_numbers:
        numbered = []
        for i, t in enumerate(tweets):
            prefix = f"({i+1}/{total}) "
            # Eger zaten numara varsa ekleme
            if t.startswith(f"({i+1}/") or t.startswith(f"{i+1}/"):
                numbered.append(t)
            else:
                # Karakter limitini kontrol et
                if len(prefix + t) <= MAX_TWEET_LEN:
                    numbered.append(prefix + t)
                else:
                    numbered.append(t)  # Uzunsa numarasiz birak
        tweets = numbered
    
    # Karakter limiti kontrolu
    for i, t in enumerate(tweets):
        if len(t) > MAX_TWEET_LEN:
            print(f"UYARI: Tweet {i+1} cok uzun ({len(t)}/{MAX_TWEET_LEN} karakter)")
            print(f"  -> {t[:50]}...")
    
    # Dry run
    if dry_run:
        print(f"\n[DRY RUN] {total} tweetlik thread:\n")
        for i, t in enumerate(tweets):
            print(f"  [{i+1}/{total}] ({len(t)} karakter)")
            print(f"  {t}")
            print()
        return []
    
    # Gercek tweet atma
    oauth = get_oauth()
    tweet_ids = []
    reply_to = None
    
    print(f"\nThread basliyor ({total} tweet)...\n")
    
    for i, text in enumerate(tweets):
        tweet_id = post_tweet(oauth, text, reply_to=reply_to)
        
        if tweet_id:
            tweet_ids.append(tweet_id)
            url = f"https://x.com/equinoxistr/status/{tweet_id}"
            print(f"  [{i+1}/{total}] OK -> {url}")
            reply_to = tweet_id
            
            # Son tweet degilse bekle
            if i < total - 1:
                time.sleep(TWEET_DELAY)
        else:
            print(f"  [{i+1}/{total}] BASARISIZ - thread durduruluyor!")
            break
    
    # Sonuc
    if len(tweet_ids) == total:
        first_url = f"https://x.com/equinoxistr/status/{tweet_ids[0]}"
        print(f"\nThread tamamlandi! {total} tweet atildi.")
        print(f"Thread linki: {first_url}")
        
        # DB'ye kaydet
        save_thread_to_db(tweet_ids, tweets)
        
        return tweet_ids
    else:
        print(f"\nThread eksik kaldi: {len(tweet_ids)}/{total} tweet atildi.")
        if tweet_ids:
            save_thread_to_db(tweet_ids, tweets[:len(tweet_ids)])
        return tweet_ids

def main():
    parser = argparse.ArgumentParser(description="FinTweet AI Thread Atma")
    parser.add_argument("tweets", nargs="*", help="Tweet metinleri (her arg bir tweet)")
    parser.add_argument("--file", "-f", help="Her satiri bir tweet olan dosya")
    parser.add_argument("--json", "-j", help="JSON dosyasi (tweets array)")
    parser.add_argument("--no-number", action="store_true", help="(1/N) numaralama ekleme")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Tweet atma, sadece goster")
    parser.add_argument("--delay", type=int, default=3, help="Tweetler arasi bekleme (saniye)")
    
    args = parser.parse_args()
    
    global TWEET_DELAY
    TWEET_DELAY = args.delay
    
    # Tweet listesini al
    tweets = []
    
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            tweets = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    elif args.json:
        with open(args.json, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                tweets = data
            elif isinstance(data, dict) and 'tweets' in data:
                tweets = data['tweets']
    elif args.tweets:
        tweets = args.tweets
    else:
        # stdin'den oku
        print("Thread tweetlerini girin (bos satir = bitis):")
        while True:
            try:
                line = input()
                if not line.strip():
                    break
                tweets.append(line.strip())
            except EOFError:
                break
    
    if not tweets:
        print("HATA: Tweet bulunamadi!")
        parser.print_help()
        sys.exit(1)
    
    post_thread(tweets, add_numbers=not args.no_number, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
