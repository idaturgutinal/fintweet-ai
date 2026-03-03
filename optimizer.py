#!/usr/bin/env python3
"""
FinTweet AI - Icerik Optimizasyonu
Engagement verilerini analiz edip gelecek hafta icin strateji onerisi verir.

Kullanim:
  python3 optimizer.py                   # Analiz + oneriler (terminal)
  python3 optimizer.py --telegram        # Telegram'a gonder
  python3 optimizer.py --update-weights  # sources.json agirliklarini guncelle
  python3 optimizer.py --ab-test "konu"  # A/B test onerileri olustur
"""

import os
import sys
import json
import sqlite3
import argparse
import requests
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# CONFIG
# ============================================================

DB_PATH = os.path.expanduser("~/.openclaw/workspace/fintweet.db")
SOURCES_PATH = os.path.expanduser("~/.openclaw/workspace/sources.json")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Minimum veri gereksinimleri
MIN_TWEETS_FOR_ANALYSIS = 10
MIN_TWEETS_PER_TYPE = 3

def init_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def get_all_engagement_data(conn, days=30):
    """Son N gunluk tum engagement verisini cek."""
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    
    c.execute("""
        SELECT t.id, t.text, t.type, t.created_at, t.source,
               COALESCE(e.likes, 0), COALESCE(e.retweets, 0),
               COALESCE(e.replies, 0), COALESCE(e.bookmarks, 0),
               COALESCE(e.impressions, 0), COALESCE(e.score, 0)
        FROM tweets t
        LEFT JOIN engagement e ON t.id = e.tweet_id
        WHERE t.created_at > ?
        ORDER BY t.created_at DESC
    """, (cutoff,))
    
    return c.fetchall()

def analyze_content_types(rows):
    """Icerik turu bazinda analiz."""
    types = defaultdict(lambda: {
        "count": 0, "scores": [], "likes": 0, "rts": 0, 
        "replies": 0, "bookmarks": 0, "impressions": 0
    })
    
    for row in rows:
        _, _, ttype, _, _, likes, rts, replies, bookmarks, impressions, score = row
        t = ttype or "bilinmiyor"
        types[t]["count"] += 1
        types[t]["scores"].append(score)
        types[t]["likes"] += likes
        types[t]["rts"] += rts
        types[t]["replies"] += replies
        types[t]["bookmarks"] += bookmarks
        types[t]["impressions"] += impressions
    
    for t in types:
        scores = types[t]["scores"]
        types[t]["avg_score"] = round(sum(scores) / len(scores), 1) if scores else 0
        types[t]["max_score"] = round(max(scores), 1) if scores else 0
        types[t]["min_score"] = round(min(scores), 1) if scores else 0
    
    return dict(types)

def analyze_timing(rows):
    """Saat bazinda analiz."""
    hours = defaultdict(lambda: {"count": 0, "scores": []})
    days = defaultdict(lambda: {"count": 0, "scores": []})
    
    for row in rows:
        _, _, _, created, _, _, _, _, _, _, score = row
        if created:
            try:
                dt = datetime.fromisoformat(created)
                h = dt.strftime("%H:00")
                d = dt.strftime("%A")
                hours[h]["count"] += 1
                hours[h]["scores"].append(score)
                days[d]["count"] += 1
                days[d]["scores"].append(score)
            except:
                pass
    
    for h in hours:
        scores = hours[h]["scores"]
        hours[h]["avg_score"] = round(sum(scores) / len(scores), 1) if scores else 0
    
    for d in days:
        scores = days[d]["scores"]
        days[d]["avg_score"] = round(sum(scores) / len(scores), 1) if scores else 0
    
    return dict(hours), dict(days)

def analyze_text_features(rows):
    """Tweet metin ozelliklerini analiz et."""
    features = {
        "short_tweets": {"count": 0, "scores": []},     # < 100 karakter
        "medium_tweets": {"count": 0, "scores": []},     # 100-200
        "long_tweets": {"count": 0, "scores": []},       # > 200
        "with_emoji": {"count": 0, "scores": []},
        "with_question": {"count": 0, "scores": []},
        "with_numbers": {"count": 0, "scores": []},
    }
    
    for row in rows:
        _, text, _, _, _, _, _, _, _, _, score = row
        if not text:
            continue
        
        length = len(text)
        if length < 100:
            features["short_tweets"]["count"] += 1
            features["short_tweets"]["scores"].append(score)
        elif length < 200:
            features["medium_tweets"]["count"] += 1
            features["medium_tweets"]["scores"].append(score)
        else:
            features["long_tweets"]["count"] += 1
            features["long_tweets"]["scores"].append(score)
        
        # Emoji var mi
        if any(ord(c) > 127 for c in text):
            features["with_emoji"]["count"] += 1
            features["with_emoji"]["scores"].append(score)
        
        # Soru var mi
        if "?" in text:
            features["with_question"]["count"] += 1
            features["with_question"]["scores"].append(score)
        
        # Sayi var mi (%, $, rakam)
        if any(c in text for c in "%$0123456789"):
            features["with_numbers"]["count"] += 1
            features["with_numbers"]["scores"].append(score)
    
    for f in features:
        scores = features[f]["scores"]
        features[f]["avg_score"] = round(sum(scores) / len(scores), 1) if scores else 0
    
    return features

def generate_strategy(type_analysis, hour_analysis, day_analysis, text_analysis, total_tweets):
    """Veri bazli strateji onerisi olustur."""
    strategy = {
        "content_mix": {},
        "best_times": [],
        "style_tips": [],
        "ab_tests": [],
    }
    
    if total_tweets < MIN_TWEETS_FOR_ANALYSIS:
        strategy["note"] = f"Henuz yeterli veri yok ({total_tweets}/{MIN_TWEETS_FOR_ANALYSIS} tweet). Daha fazla tweet at."
        return strategy
    
    # Icerik miksi onerisi
    if type_analysis:
        sorted_types = sorted(type_analysis.items(), key=lambda x: x[1]["avg_score"], reverse=True)
        total_weight = 0
        for ttype, stats in sorted_types:
            # Skora gore agirlik ata
            weight = max(0.05, stats["avg_score"] / sum(s["avg_score"] for _, s in sorted_types if s["avg_score"] > 0)) if any(s["avg_score"] > 0 for _, s in sorted_types) else 0.15
            strategy["content_mix"][ttype] = round(weight, 2)
            total_weight += weight
        
        # Normalize et
        if total_weight > 0:
            for t in strategy["content_mix"]:
                strategy["content_mix"][t] = round(strategy["content_mix"][t] / total_weight, 2)
    
    # En iyi saatler
    if hour_analysis:
        best_hours = sorted(hour_analysis.items(), key=lambda x: x[1]["avg_score"], reverse=True)[:3]
        strategy["best_times"] = [{"hour": h, "avg_score": s["avg_score"], "count": s["count"]} for h, s in best_hours]
    
    # Stil onerileri
    if text_analysis:
        short_avg = text_analysis["short_tweets"]["avg_score"]
        long_avg = text_analysis["long_tweets"]["avg_score"]
        
        if short_avg > long_avg * 1.3:
            strategy["style_tips"].append("Kisa tweetler daha iyi performans gosteriyor. Ozlu ve vurucu yaz.")
        elif long_avg > short_avg * 1.3:
            strategy["style_tips"].append("Uzun/detayli tweetler daha iyi. Thread ve analiz icerikleri arttir.")
        
        if text_analysis["with_question"]["avg_score"] > text_analysis["with_numbers"]["avg_score"]:
            strategy["style_tips"].append("Soru soran tweetler etkilesim aliyor. Daha fazla soru sor.")
        
        if text_analysis["with_numbers"]["count"] > 0 and text_analysis["with_numbers"]["avg_score"] > 0:
            strategy["style_tips"].append("Veri ve rakam iceren tweetler iyi performans gosteriyor.")
    
    # A/B test onerileri
    if type_analysis:
        for ttype, stats in type_analysis.items():
            if stats["count"] >= MIN_TWEETS_PER_TYPE and stats["max_score"] > stats["avg_score"] * 2:
                strategy["ab_tests"].append(f"{ttype}: Yuksek varyans var. Farkli tonlari test et.")
    
    return strategy

def update_source_weights(strategy):
    """sources.json'daki content_types agirliklarini guncelle."""
    if not os.path.exists(SOURCES_PATH):
        print(f"HATA: {SOURCES_PATH} bulunamadi!")
        return False
    
    with open(SOURCES_PATH, 'r', encoding='utf-8') as f:
        sources = json.load(f)
    
    if "content_types" not in sources:
        print("HATA: content_types bulunamadi!")
        return False
    
    content_mix = strategy.get("content_mix", {})
    if not content_mix:
        print("Yeterli veri yok, agirliklar guncellenemedi.")
        return False
    
    # Mevcut turleri guncelle
    type_map = {
        "haber_yorumu": ["Haber", "haber", "haber_yorumu"],
        "bilgilendirici": ["Bilgi", "bilgi", "bilgilendirici"],
        "alinti": ["Alinti", "alinti"],
        "analiz_thread": ["Analiz", "analiz", "thread", "analiz_thread"],
        "onchain_veri": ["On-chain", "onchain", "onchain_veri"],
        "makro_ekonomi": ["Makro", "makro", "makro_ekonomi"],
        "mizah_kultur": ["Kultur", "mizah", "mizah_kultur"],
    }
    
    updated = False
    for config_key, aliases in type_map.items():
        if config_key in sources["content_types"]:
            for alias in aliases:
                if alias in content_mix:
                    sources["content_types"][config_key]["weight"] = content_mix[alias]
                    updated = True
                    break
    
    if updated:
        # Backup
        backup_path = SOURCES_PATH + ".bak"
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(sources, f, ensure_ascii=False, indent=2)
        
        with open(SOURCES_PATH, 'w', encoding='utf-8') as f:
            json.dump(sources, f, ensure_ascii=False, indent=2)
        
        print(f"sources.json guncellendi! (backup: {backup_path})")
        return True
    
    return False

def format_output(type_analysis, hour_analysis, text_analysis, strategy, total_tweets):
    """Terminal ciktisi."""
    lines = []
    lines.append("=" * 60)
    lines.append("  FINTWEET AI - ICERIK OPTIMIZASYONU")
    lines.append("=" * 60)
    lines.append(f"\n  Toplam analiz edilen tweet: {total_tweets}\n")
    
    # Icerik turu performansi
    lines.append("  ICERIK TURU PERFORMANSI:")
    lines.append(f"  {'Tur':<20} {'Sayi':<8} {'Ort.Skor':<10} {'Max':<8}")
    lines.append("  " + "-" * 46)
    for ttype, stats in sorted(type_analysis.items(), key=lambda x: x[1]["avg_score"], reverse=True):
        lines.append(f"  {ttype:<20} {stats['count']:<8} {stats['avg_score']:<10} {stats['max_score']:<8}")
    
    # Metin analizi
    lines.append("\n  METIN OZELLIKLERI:")
    for feat, stats in text_analysis.items():
        if stats["count"] > 0:
            label = feat.replace("_", " ").title()
            lines.append(f"    {label}: {stats['count']}x, ort. skor: {stats['avg_score']}")
    
    # Strateji
    lines.append("\n  STRATEJI ONERILERI:")
    if strategy.get("note"):
        lines.append(f"    {strategy['note']}")
    else:
        if strategy.get("content_mix"):
            lines.append("    Icerik Miksi:")
            for t, w in sorted(strategy["content_mix"].items(), key=lambda x: x[1], reverse=True):
                lines.append(f"      {t}: %{int(w*100)}")
        
        if strategy.get("best_times"):
            lines.append("    En Iyi Saatler:")
            for bt in strategy["best_times"]:
                lines.append(f"      {bt['hour']} (ort: {bt['avg_score']}, {bt['count']} tweet)")
        
        if strategy.get("style_tips"):
            lines.append("    Stil Onerileri:")
            for tip in strategy["style_tips"]:
                lines.append(f"      -> {tip}")
        
        if strategy.get("ab_tests"):
            lines.append("    A/B Test Onerileri:")
            for test in strategy["ab_tests"]:
                lines.append(f"      -> {test}")
    
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)

def format_telegram(strategy, total_tweets):
    """Telegram formatli strateji."""
    lines = []
    lines.append("🧠 [STRATEJI] Icerik Optimizasyonu")
    lines.append(f"📊 {total_tweets} tweet analiz edildi\n")
    
    if strategy.get("note"):
        lines.append(f"⚠️ {strategy['note']}")
    else:
        if strategy.get("content_mix"):
            lines.append("📋 Onerilen Icerik Miksi:")
            for t, w in sorted(strategy["content_mix"].items(), key=lambda x: x[1], reverse=True):
                bar = "█" * int(w * 20)
                lines.append(f"  {t}: {bar} %{int(w*100)}")
        
        if strategy.get("best_times"):
            lines.append("\n⏰ En Iyi Saatler:")
            for bt in strategy["best_times"]:
                lines.append(f"  {bt['hour']} (skor: {bt['avg_score']})")
        
        if strategy.get("style_tips"):
            lines.append("\n💡 Stil:")
            for tip in strategy["style_tips"]:
                lines.append(f"  → {tip}")
    
    return "\n".join(lines)

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("HATA: Telegram config eksik!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})
    return resp.status_code == 200

def main():
    parser = argparse.ArgumentParser(description="FinTweet AI Icerik Optimizasyonu")
    parser.add_argument("--days", type=int, default=30, help="Analiz suresi (gun)")
    parser.add_argument("--telegram", action="store_true", help="Telegram'a gonder")
    parser.add_argument("--update-weights", action="store_true", help="sources.json agirliklarini guncelle")
    parser.add_argument("--ab-test", type=str, help="Belirli konu icin A/B test onerileri")
    
    args = parser.parse_args()
    
    conn = init_db()
    rows = get_all_engagement_data(conn, days=args.days)
    conn.close()
    
    total_tweets = len(rows)
    
    if not rows:
        print("Veri bulunamadi. Once tweet at ve engagement olcumu yap.")
        return
    
    type_analysis = analyze_content_types(rows)
    hour_analysis, day_analysis = analyze_timing(rows)
    text_analysis = analyze_text_features(rows)
    strategy = generate_strategy(type_analysis, hour_analysis, day_analysis, text_analysis, total_tweets)
    
    # Terminal ciktisi
    print(format_output(type_analysis, hour_analysis, text_analysis, strategy, total_tweets))
    
    # Telegram
    if args.telegram:
        tg_text = format_telegram(strategy, total_tweets)
        if send_telegram(tg_text):
            print("Strateji Telegram'a gonderildi!")
    
    # Agirlik guncelleme
    if args.update_weights:
        update_source_weights(strategy)

if __name__ == "__main__":
    main()
