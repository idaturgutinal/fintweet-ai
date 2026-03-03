#!/usr/bin/env python3
"""
sources.json'a twitter_sources ekler.
Mevcut kaynaklari bozmadan sadece twitter_sources blogu ekler/gunceller.
"""

import os
import json

SOURCES_PATH = os.path.expanduser("~/.openclaw/workspace/sources.json")

TWITTER_SOURCES = {
    "breaking_news": {
        "label": "Son Dakika Haberleri",
        "priority": "high",
        "scan_interval_hours": 2,
        "max_tweets_per_scan": 3,
        "accounts": [
            "@WatcherGuru",
            "@Bitcoin_Archive",
            "@BitcoinMagazine",
            "@CoinDesk",
            "@Cointelegraph",
            "@CryptoSlate",
        ]
    },
    "whale_alerts": {
        "label": "Whale & On-chain",
        "priority": "high",
        "scan_interval_hours": 1,
        "max_tweets_per_scan": 5,
        "accounts": [
            "@whale_alert",
            "@lookonchain",
            "@EmberCN",
            "@spotonchain",
        ]
    },
    "macro_economy": {
        "label": "Makro Ekonomi",
        "priority": "medium",
        "scan_interval_hours": 4,
        "max_tweets_per_scan": 3,
        "accounts": [
            "@zaborpress",
            "@NickTimiraos",
            "@DeItaone",
            "@ForexLive",
            "@ReutersBiz",
        ]
    },
    "crypto_analysis": {
        "label": "Kripto Analiz",
        "priority": "medium",
        "scan_interval_hours": 6,
        "max_tweets_per_scan": 3,
        "accounts": [
            "@100trillionUSD",
            "@WClementeIII",
            "@glassnodealerts",
            "@CryptoBirb",
            "@CryptoCapo_",
        ]
    },
    "turkey_crypto": {
        "label": "Türkiye Kripto",
        "priority": "medium",
        "scan_interval_hours": 4,
        "max_tweets_per_scan": 3,
        "accounts": [
            "@BTCHaber",
            "@Koinbulteni",
            "@coinotag",
            "@KriptoParaHaber",
        ]
    },
    "influential": {
        "label": "Etkili Isimler",
        "priority": "low",
        "scan_interval_hours": 8,
        "max_tweets_per_scan": 2,
        "accounts": [
            "@VitalikButerin",
            "@caborek",
            "@michael_saylor",
            "@APompliano",
        ]
    }
}

def update_sources():
    if not os.path.exists(SOURCES_PATH):
        print(f"HATA: {SOURCES_PATH} bulunamadi!")
        return
    
    # Backup
    with open(SOURCES_PATH, 'r', encoding='utf-8') as f:
        sources = json.load(f)
    
    backup_path = SOURCES_PATH + ".bak2"
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)
    
    # Twitter sources ekle
    sources['twitter_sources'] = TWITTER_SOURCES
    
    with open(SOURCES_PATH, 'w', encoding='utf-8') as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)
    
    # Ozet
    total_accounts = sum(len(cat['accounts']) for cat in TWITTER_SOURCES.values())
    print(f"sources.json guncellendi!")
    print(f"  {len(TWITTER_SOURCES)} kategori, {total_accounts} hesap eklendi:")
    for key, cat in TWITTER_SOURCES.items():
        print(f"    {cat['label']}: {', '.join(cat['accounts'])}")

if __name__ == "__main__":
    update_sources()
