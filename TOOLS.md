# TOOLS.md - FinTweet AI Araçları

## Tweet Atma
```bash
python3 tweet.py "metin"                                    # Normal tweet
python3 tweet.py "metin" --media img.png                    # Görselli tweet
python3 tweet.py "metin" --media img.png --alt "açıklama"   # Alt text ile
python3 tweet.py "yorum" --quote TWEET_ID                   # Quote tweet
python3 tweet.py "yorum" --quote TWEET_ID --media img.png   # Quote + grafik
python3 tweet.py "cevap" --reply-to TWEET_ID                # Reply
```

## Twitter Okuma (twitter_reader.py)
```bash
python3 twitter_reader.py --accounts @whale_alert @WatcherGuru --max 5   # Belirli hesaplar
python3 twitter_reader.py --category whale_onchain --max 5               # Kategoriye göre
python3 twitter_reader.py --all --max 5                                  # Tüm kaynaklar
python3 twitter_reader.py --search "bitcoin ETF" --max 10                # Tweet ara
python3 twitter_reader.py --cost                                         # API maliyet tahmini
```

### Kaynak Kategorileri (sources.json)
- **breaking_news:** @WatcherGuru, @Bitcoin_Archive, @BitcoinMagazine, @CoinDesk, @Cointelegraph, @CryptoSlate, @WuBlockchain
- **whale_onchain:** @whale_alert, @lookonchain, @EmberCN, @spotonchain
- **macro:** @zaborpress, @NickTimiraos, @DeItaone, @ForexLive, @ReutersBiz
- **crypto_analysis:** @100trillionUSD, @WClementeIII, @glassnodealerts, @CryptoBirb, @Ashcryptoreal
- **turkey_crypto:** @BTCHaber, @Koinbulteni, @coinotag, @KriptoParaHaber
- **influencers:** @VitalikButerin, @caborek, @michael_saylor, @APompliano
- **etf_tracking:** @EricBalchunas, @JSeyff, @NateGeraci

## Thread Atma
```bash
python3 thread.py "tweet1" "tweet2" "tweet3"              # Thread at
python3 thread.py --dry-run "tweet1" "tweet2" "tweet3"    # Önizleme
```

## Diğer Araçlar
```bash
python3 scanner.py                             # Web kaynak tarama
python3 engagement.py --tweet-id XXXXX         # Engagement ölç
python3 reporter.py                            # Haftalık rapor
python3 reporter.py --telegram                 # Raporu Telegram'a gönder
python3 optimizer.py                           # İçerik optimizasyonu
python3 optimizer.py --telegram --update-weights  # Ağırlıkları güncelle
python3 update_sources.py                      # Twitter kaynaklarını güncelle
python3 alert_monitor.py                       # Acil durum monitörü (systemd servisi)
```

## Ortam
- **Workspace:** ~/.openclaw/workspace/
- **DB:** fintweet.db (findings, tweets, twitter_cache, api_usage)
- **Bulgular:** findings/ klasörü
- **Kaynaklar:** sources.json
- **Env:** ~/.fintweet-env (source edilmeli)

---

## XPatla API (xpatla.py)

Viral tweet üretme, quote tweet ve reply önerileri.

### Tweet Üret
```
python3 xpatla.py --generate "bitcoin" --format punch --count 3
python3 xpatla.py --generate "ethereum" --persona news --tone raw
python3 xpatla.py --generate "yapay zeka" --image
python3 xpatla.py --generate "kripto" --telegram
```

### Quote Tweet Üret
```
python3 xpatla.py --quote "tweet metni" --author kullanici_adi
python3 xpatla.py --quote "BTC 100k" --author Bitcoin_Archive --format spark
```

### Reply Üret
```
python3 xpatla.py --reply "tweet metni" --author kullanici_adi --reply-tone insightful
```

### Kredi Bakiyesi
```
python3 xpatla.py --credits
```

### Formatlar
micro, punch, classic, spark, storm, longform, thunder, mega

### Personalar
authority, news, shitpost, mentalist, bilgi, sigma, doomer, hustler

### Tonlar (tweet): default, raw, polished, unhinged, deadpan
### Tonlar (reply): supportive, witty, insightful, provocative

### Kredi Tablosu
Punch=3 | Spark=5 | Storm=7 | Thunder=10 | Quote=6 | Reply=6 | Görsel=+5

### Rate Limit: 30/dakika, 1000/gün

## Otomatik XPatla (auto_xpatla.py)
Scanner bulgularından otomatik tweet önerisi üretir.
Günde 4 kez çalışır (07:35, 12:05, 17:05, 21:35 TR).
7/24 aktif (kripto piyasası durmuyor).

```bash
python3 auto_xpatla.py              # Normal çalıştır
python3 auto_xpatla.py --dry-run    # Test (API çağrısı yapmaz)
python3 auto_xpatla.py --force      # Günlük limit kontrolünü bypass et
```

Günlük max 4 çağrı | Skor eşiği: 100 | Count: 1 tweet/çağrı
Tahmini kredi: ~12-20/gün, ~400-600/ay (1500 aylık bütçeden)

## Telegram Komutları (telegram_commands.py)

Telegram'dan tweet yönetimi. Öneriler DB'de `telegram_suggestions` tablosunda tutulur.

```bash
python3 telegram_commands.py "at 7"              # 7 numaralı öneriyi tweet olarak at
python3 telegram_commands.py "at"                 # Son pending öneriyi at
python3 telegram_commands.py "atma 7"             # 7 numaralı öneriyi reddet
python3 telegram_commands.py "düzenle 7: metin"   # Düzenle ve at
python3 telegram_commands.py "quote 7: yorum"     # Quote tweet (kaynak: önerinin source_url'si)
python3 telegram_commands.py "reply 7: cevap"     # Reply (kaynak: önerinin source_url'si)
python3 telegram_commands.py "kredi"              # XPatla kredi bakiyesi
python3 telegram_commands.py "durum"              # Sistem durumu
python3 telegram_commands.py "son"                # Son 5 öneri
python3 telegram_commands.py "tweet: metin"       # Direkt tweet at (öneri sisteminden bağımsız)
```

### Kısayollar
- Sadece rakam (`7`) → at komutu
- `0` → atma (son öneriyi reddet)

### DB: telegram_suggestions
Kolonlar: id, text, source_url, source_tweet_id, category, created_at, status
Status: pending | sent | rejected | edited
