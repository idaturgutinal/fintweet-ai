#!/usr/bin/env python3
"""
FinTweet AI - Acil Durum Dedektoru (alert_monitor.py)
7/24 calisan daemon. Fiyat degisimi, whale hareketi, regulasyon haberi gibi
acil durumlari tespit edip Telegram'a bildirim gonderir.

Kullanim:
  python3 alert_monitor.py              # Daemon olarak calistir
  python3 alert_monitor.py --once       # Tek sefer kontrol et ve cik
  python3 alert_monitor.py --test       # Test modu (Telegram'a test mesaji)

Systemd service olarak kurulum:
  sudo cp fintweet-alert.service /etc/systemd/system/
  sudo systemctl enable fintweet-alert
  sudo systemctl start fintweet-alert
"""

import os
import sys
import json
import time
import signal
import sqlite3
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw" / "workspace"
DB_FILE = WORKSPACE / "fintweet.db"
ALERT_LOG = WORKSPACE / "alerts.log"
FINDINGS_DIR = WORKSPACE / "findings"
FINDINGS_DIR.mkdir(exist_ok=True)

# --- Binance Proxy (localhost:3100) veya dogrudan API ---
BINANCE_PROXY = "http://localhost:3100"
BINANCE_API = "https://api.binance.com"

# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8507724793:AAGNfRnkQ5EGkqRHUFWMtlZxvmhAXcouxEo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", None)  # Env veya otomatik

# --- Esik Degerleri ---
PRICE_CHANGE_THRESHOLD = 5.0    # %5 fiyat degisimi
WHALE_BTC_THRESHOLD = 1000      # 1000 BTC
WHALE_ETH_THRESHOLD = 10000     # 10000 ETH
CHECK_INTERVAL = 60             # Saniye (varsayilan)

# --- Durum ---
last_prices = {}
alert_cooldowns = {}  # Ayni alarm icin tekrar onleme
running = True


def log_alert(msg):
    """Alert log dosyasina yaz."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(ALERT_LOG, "a") as f:
        f.write(line + "\n")


def get_prices():
    """BTC ve ETH fiyatlarini al (once binance-proxy, sonra dogrudan API)."""
    import requests

    symbols = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}
    prices = {}

    for symbol, label in symbols.items():
        try:
            # Once binance proxy dene
            resp = requests.get(
                f"{BINANCE_PROXY}/api/v3/ticker/24hr",
                params={"symbol": symbol},
                timeout=5,
            )
            if resp.status_code != 200:
                raise Exception("Proxy failed")
            data = resp.json()
        except Exception:
            try:
                # Dogrudan Binance API
                resp = requests.get(
                    f"{BINANCE_API}/api/v3/ticker/24hr",
                    params={"symbol": symbol},
                    timeout=10,
                )
                data = resp.json()
            except Exception as e:
                log_alert(f"[HATA] Fiyat alinamadi ({label}): {e}")
                continue

        prices[label] = {
            "price": float(data.get("lastPrice", 0)),
            "change_pct": float(data.get("priceChangePercent", 0)),
            "high_24h": float(data.get("highPrice", 0)),
            "low_24h": float(data.get("lowPrice", 0)),
            "volume": float(data.get("volume", 0)),
        }

    return prices


def check_price_alerts(prices):
    """Fiyat degisimi kontrolu."""
    global last_prices
    alerts = []

    for symbol, data in prices.items():
        current = data["price"]
        change = data["change_pct"]

        # 24 saatlik degisim kontrolu
        if abs(change) >= PRICE_CHANGE_THRESHOLD:
            direction = "yukselis" if change > 0 else "dusus"
            alert_key = f"price_{symbol}_{direction}_{int(abs(change))}"

            if not is_cooldown(alert_key, cooldown_minutes=60):
                alerts.append({
                    "type": "price_alert",
                    "priority": "high" if abs(change) >= 7 else "medium",
                    "symbol": symbol,
                    "price": current,
                    "change_pct": round(change, 2),
                    "direction": direction,
                    "high_24h": data["high_24h"],
                    "low_24h": data["low_24h"],
                    "message": f"🚨 {symbol} %{abs(change):.1f} {direction}!\n"
                               f"Fiyat: ${current:,.0f}\n"
                               f"24s Aralik: ${data['low_24h']:,.0f} - ${data['high_24h']:,.0f}",
                })
                set_cooldown(alert_key, 60)

        # Onceki fiyatla karsilastirma (kisa vadeli ani hareket)
        if symbol in last_prices:
            prev = last_prices[symbol]
            if prev > 0:
                short_change = ((current - prev) / prev) * 100
                if abs(short_change) >= 3.0:  # %3 kisa vadeli hareket
                    direction = "yukselis" if short_change > 0 else "dusus"
                    alert_key = f"short_price_{symbol}_{direction}"

                    if not is_cooldown(alert_key, cooldown_minutes=30):
                        alerts.append({
                            "type": "price_alert_short",
                            "priority": "high",
                            "symbol": symbol,
                            "price": current,
                            "change_pct": round(short_change, 2),
                            "direction": direction,
                            "message": f"⚡ {symbol} kisa surede %{abs(short_change):.1f} {direction}!\n"
                                       f"Fiyat: ${current:,.0f} (onceki kontrol: ${prev:,.0f})",
                        })
                        set_cooldown(alert_key, 30)

        last_prices[symbol] = current

    return alerts


def check_whale_alerts():
    """Whale Alert kontrolu (Brave Search ile)."""
    import requests

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return []

    alerts = []
    queries = [
        "whale alert large bitcoin transfer today",
        "whale alert large ethereum transfer today",
    ]

    for query in queries:
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                params={"q": query, "count": 3, "freshness": "ph"},  # Son 1 saat
                timeout=10,
            )

            if resp.status_code != 200:
                continue

            data = resp.json()
            for item in data.get("web", {}).get("results", []):
                title = item.get("title", "").lower()
                snippet = item.get("description", "")

                # Basit filtre: buyuk transfer haberi mi?
                if any(kw in title for kw in ["whale", "transfer", "moved", "million", "billion"]):
                    alert_key = f"whale_{hashlib.md5(title.encode()).hexdigest()[:8]}"

                    if not is_cooldown(alert_key, cooldown_minutes=120):
                        alerts.append({
                            "type": "whale_movement",
                            "priority": "high",
                            "title": item.get("title", ""),
                            "snippet": snippet,
                            "url": item.get("url", ""),
                            "message": f"🐋 Whale Hareketi Tespit Edildi!\n\n"
                                       f"{item.get('title', '')}\n"
                                       f"{snippet[:200]}\n"
                                       f"Kaynak: {item.get('url', '')}",
                        })
                        set_cooldown(alert_key, 120)

        except Exception as e:
            log_alert(f"[HATA] Whale alert kontrol hatasi: {e}")

    return alerts


def check_breaking_news():
    """Son dakika haber kontrolu (Brave Search ile)."""
    import requests

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return []

    alerts = []
    queries = [
        "SEC cryptocurrency breaking news",
        "bitcoin regulation breaking news",
        "crypto hack exploit today",
        "TCMB faiz karari son dakika",
        "federal reserve emergency announcement",
    ]

    for query in queries:
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                params={"q": query, "count": 3, "freshness": "ph"},
                timeout=10,
            )

            if resp.status_code != 200:
                continue

            data = resp.json()
            for item in data.get("web", {}).get("results", []):
                title = item.get("title", "").lower()
                snippet = item.get("description", "")

                # Aciliyet filtresi
                urgent_keywords = [
                    "breaking", "urgent", "just in", "son dakika",
                    "hack", "exploit", "sec approves", "sec rejects",
                    "emergency", "crash", "surge", "acil",
                ]

                if any(kw in title for kw in urgent_keywords):
                    alert_key = f"news_{hashlib.md5(title.encode()).hexdigest()[:8]}"

                    if not is_cooldown(alert_key, cooldown_minutes=180):
                        alerts.append({
                            "type": "breaking_news",
                            "priority": "critical",
                            "title": item.get("title", ""),
                            "snippet": snippet,
                            "url": item.get("url", ""),
                            "message": f"📰 SON DAKIKA!\n\n"
                                       f"{item.get('title', '')}\n"
                                       f"{snippet[:200]}\n"
                                       f"Kaynak: {item.get('url', '')}",
                        })
                        set_cooldown(alert_key, 180)

        except Exception as e:
            log_alert(f"[HATA] Breaking news kontrol hatasi: {e}")

    return alerts


def is_cooldown(key, cooldown_minutes=60):
    """Alarm tekrar onleme kontrolu."""
    if key in alert_cooldowns:
        elapsed = time.time() - alert_cooldowns[key]
        if elapsed < cooldown_minutes * 60:
            return True
    return False


def set_cooldown(key, minutes):
    """Alarm cooldown ayarla."""
    alert_cooldowns[key] = time.time()


def send_telegram_alert(alert):
    """Telegram'a acil durum bildirimi gonder."""
    import requests

    # Bot token'i al
    token = TELEGRAM_BOT_TOKEN

    # Chat ID'yi bulmak icin getUpdates kullan
    chat_id = get_telegram_chat_id(token)
    if not chat_id:
        log_alert("[HATA] Telegram Chat ID bulunamadi!")
        return False

    priority_emoji = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
    }

    priority = alert.get("priority", "medium")
    emoji = priority_emoji.get(priority, "⚪")

    text = f"{emoji} [{priority.upper()}] ACIL UYARI\n\n"
    text += alert.get("message", "Detay yok")
    text += f"\n\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    text += "\n\n💬 Tweet taslagi olusturmami ister misiniz?"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log_alert(f"[TELEGRAM] Alert gonderildi: {alert.get('type')}")
            return True
        else:
            log_alert(f"[HATA] Telegram gonderim hatasi: {resp.status_code}")
            return False
    except Exception as e:
        log_alert(f"[HATA] Telegram hatasi: {e}")
        return False


def get_telegram_chat_id(token):
    """Son mesajdan chat ID al."""
    import requests

    global TELEGRAM_CHAT_ID
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID

    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
        data = resp.json()
        if data.get("result"):
            TELEGRAM_CHAT_ID = data["result"][-1]["message"]["chat"]["id"]
            return TELEGRAM_CHAT_ID
    except Exception:
        pass

    return None


def save_alert_to_db(conn, alert):
    """Alarmi veritabanina kaydet."""
    try:
        h = hashlib.md5(json.dumps(alert, sort_keys=True).encode()).hexdigest()[:16]
        conn.execute("""
            INSERT OR IGNORE INTO findings 
            (hash, source_type, source_category, source_name, title, snippet, url, raw_data, relevance_score)
            VALUES (?, 'alert', ?, ?, ?, ?, ?, ?, ?)
        """, (
            h,
            alert.get("type", "unknown"),
            alert.get("symbol", alert.get("source", "")),
            alert.get("title", alert.get("type", "")),
            alert.get("message", ""),
            alert.get("url", ""),
            json.dumps(alert),
            100 if alert.get("priority") == "critical" else 80,
        ))
        conn.commit()
    except Exception as e:
        log_alert(f"[HATA] DB kayit hatasi: {e}")


def signal_handler(sig, frame):
    """Graceful shutdown."""
    global running
    log_alert("[STOP] Alert monitor durduruluyor...")
    running = False


def run_monitor(once=False):
    """Ana izleme dongusu."""
    global running
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log_alert("[START] FinTweet Alert Monitor baslatildi")

    # DB baglantisi
    conn = sqlite3.connect(str(DB_FILE))

    cycle = 0
    while running:
        cycle += 1
        all_alerts = []

        # Her dongude fiyat kontrol
        try:
            prices = get_prices()
            if prices:
                price_alerts = check_price_alerts(prices)
                all_alerts.extend(price_alerts)

                # Fiyat bilgisini logla (her 10 dongude bir)
                if cycle % 10 == 0:
                    for sym, data in prices.items():
                        log_alert(f"[FIYAT] {sym}: ${data['price']:,.0f} ({data['change_pct']:+.1f}%)")
        except Exception as e:
            log_alert(f"[HATA] Fiyat kontrol hatasi: {e}")

        # Her 5 dongude whale kontrolu (5 dakikada bir)
        if cycle % 5 == 0:
            try:
                whale_alerts = check_whale_alerts()
                all_alerts.extend(whale_alerts)
            except Exception as e:
                log_alert(f"[HATA] Whale kontrol hatasi: {e}")

        # Her 10 dongude breaking news kontrolu (10 dakikada bir)
        if cycle % 10 == 0:
            try:
                news_alerts = check_breaking_news()
                all_alerts.extend(news_alerts)
            except Exception as e:
                log_alert(f"[HATA] News kontrol hatasi: {e}")

        # Alarmlari isle
        for alert in all_alerts:
            log_alert(f"[ALERT] {alert['type']}: {alert.get('title', alert.get('symbol', ''))}")
            save_alert_to_db(conn, alert)
            send_telegram_alert(alert)

        if once:
            break

        time.sleep(CHECK_INTERVAL)

    conn.close()
    log_alert("[STOP] Alert Monitor durduruldu.")


def test_mode():
    """Test modu - Telegram'a test mesaji gonder."""
    log_alert("[TEST] Test modu baslatildi")

    # Fiyat kontrolu
    prices = get_prices()
    if prices:
        for sym, data in prices.items():
            print(f"  {sym}: ${data['price']:,.0f} ({data['change_pct']:+.1f}%)")

    # Test mesaji
    test_alert = {
        "type": "test",
        "priority": "medium",
        "message": "🧪 FinTweet Alert Monitor TEST\n\n"
                   "Bu bir test mesajidir.\n"
                   f"BTC: ${prices.get('BTC', {}).get('price', 0):,.0f}\n"
                   f"ETH: ${prices.get('ETH', {}).get('price', 0):,.0f}\n\n"
                   "Alert sistemi calisiyor!",
    }

    success = send_telegram_alert(test_alert)
    print(f"  Telegram gonderim: {'Basarili' if success else 'Basarisiz'}")


def main():
    parser = argparse.ArgumentParser(description="FinTweet AI Alert Monitor")
    parser.add_argument("--once", action="store_true", help="Tek sefer kontrol et ve cik")
    parser.add_argument("--test", action="store_true", help="Test modu")
    parser.add_argument("--interval", type=int, default=60, help="Kontrol araligi (saniye)")
    args = parser.parse_args()

    global CHECK_INTERVAL
    CHECK_INTERVAL = args.interval

    if args.test:
        test_mode()
    else:
        run_monitor(once=args.once)


if __name__ == "__main__":
    main()
