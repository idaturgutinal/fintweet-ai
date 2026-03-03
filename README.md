# FinTweet AI

**Autonomous financial content pipeline for Turkish crypto/finance Twitter (@equinoxistr).**

FinTweet AI scans news sources, generates tweet drafts using LLMs, validates them for grammar and accuracy, routes them through a Telegram approval workflow, and publishes to Twitter — all running 24/7 on a VPS.

---

## How It Works

```
Scanner → Auto XPatla → Tweet Validator → Telegram Bot → Twitter
(Brave+API)  (LLM+Dedup)  (Grammar+Accuracy) (Approve/Edit)  (Post)
```

### Pipeline

1. **Scanner** — Crawls news sources (Brave Search + Twitter API v2) every 3 hours across 6 time slots.
2. **Auto XPatla** — Generates tweet drafts via Claude API. Deduplication with difflib (>60% similarity = skip). Applies persona rules from SOUL.md.
3. **Tweet Validator** — Claude Haiku validates every draft before it reaches Telegram:
   - Turkish grammar and spelling check
   - Foreign word + Turkish suffix rules (suffixes follow pronunciation, not spelling: Bitcoin'in, Ethereum'un, Trump'ın)
   - Source-content accuracy verification (accuracy < 70 = reject)
4. **Telegram Bot** — Sends validated drafts with inline buttons: Approve, Reject, Edit, Quote.
5. **Smart Auto-Approve** — Drafts scoring >=75 enter the auto-approve candidate pool:
   - Prioritization: quote tweets > highest score > freshest news
   - Only 1 auto-approve per cron run
   - Anti-bot cooldown: 45-90 min random delay between auto-approvals
6. **Tweet Publisher** — Posts via Twitter OAuth 1.0a. Quote tweet 403 fallback: if quoting is restricted by the source account, automatically posts as regular tweet with source link appended.
7. **Engagement Tracker** — Collects metrics (likes, retweets, replies, impressions) for optimization feedback.

---

## Key Features

| Feature | Description |
|---|---|
| Tweet Validator | 3-layer quality gate: grammar, foreign word suffixes, content accuracy |
| Anti-Bot Cooldown | 45-90 min random delay between auto-approved tweets |
| Smart Prioritization | Quote tweets > high score > fresh news, max 1 auto-approve per run |
| Quote 403 Fallback | Restricted quotes auto-convert to regular tweet + source link |
| Dedup Detection | difflib >60% similarity to recent posts = skip |
| SOUL Persona | Multi-dimensional voice: format x persona x tone |
| Error Alerting | All scripts send Telegram alerts on failure |
| DB Backup | Daily automated backup with 7-day retention |

---

## Architecture

### Core Scripts

| Script | Purpose | Schedule |
|---|---|---|
| scanner.py | News crawling (Brave + Twitter API) | Every 3h, 6 slots |
| auto_xpatla.py | Tweet generation + auto-approve + cooldown | 8 category-matched slots |
| tweet_validator.py | Grammar + suffix rules + accuracy check | Called by auto_xpatla |
| telegram_bot.py | Long-polling Telegram bot | 24/7 daemon |
| telegram_commands.py | Command handler (approve/reject/edit/quote) | Used by telegram_bot |
| tweet.py | Twitter publisher (403 fallback) | On-demand |
| xpatla.py | Claude/XPatla API integration | Used by auto_xpatla |
| alert_monitor.py | Price/whale/news alerts | 24/7 daemon (60s) |

### Supporting Scripts

| Script | Purpose | Schedule |
|---|---|---|
| morning_summary.py | Daily summary tweet via Claude API | Daily 07:15 TR |
| engagement_tracker.py | Tweet performance metrics | Every 2h |
| weekly_report.py | Weekly performance report | Sundays 20:00 TR |
| optimizer.py | Monthly content strategy | 1st of month |
| error_notifier.py | Telegram error alerts | On exception |
| thread.py | Reply chain utility | Manual |
| twitter_reader.py | Twitter account reader | Used by scanner |
| update_sources.py | Source config updater | Manual |

### Slot-Category Mapping

| Slot | UTC | TR | Categories |
|---|---|---|---|
| morning_macro | 04:30 | 07:30 | Macro, breaking, Turkey |
| crypto_analysis | 06:00 | 09:00 | Crypto analysis, ETF |
| breaking_onchain | 08:00 | 11:00 | Breaking, on-chain, whale |
| turkey_regulation | 10:30 | 13:30 | Turkish economy, regulation |
| defi_altcoin | 12:00 | 15:00 | DeFi, altcoin, stablecoin |
| us_market_open | 13:30 | 16:30 | US markets, macro |
| whale_social | 16:30 | 19:30 | Whale alerts, social signals |
| night_global | 19:00 | 22:00 | Geopolitics, AI, science |

---

## Database Schema

| Table | Purpose |
|---|---|
| findings | Crawled news items with scores |
| scan_log | Scanner execution history |
| twitter_cache | Twitter API response cache |
| auto_xpatla_log | Tweet generation history |
| xpatla_generations | LLM API call records |
| telegram_suggestions | Generated draft tweets |
| tweets | Published tweets |
| tweet_engagement | Engagement metrics per tweet |
| api_usage | API usage tracking |

---

## Tech Stack

- Python 3, SQLite
- Claude API (Haiku for validation, Sonnet for generation)
- Twitter API v2 (OAuth 1.0a), Telegram Bot API
- Brave Search API, XPatla API
- Hetzner VPS (Ubuntu 24), cron scheduling

---

## Setup
```bash
git clone https://github.com/idaturgutinal/fintweet-ai.git
cd fintweet-ai
cp .env.example .env
pip install requests tweepy
python3 scanner.py --init
nohup python3 telegram_bot.py &
nohup python3 alert_monitor.py --interval 60 &
```

### Required Environment Variables

`TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`, `TWITTER_BEARER_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `BRAVE_API_KEY`, `ANTHROPIC_API_KEY`, `XPATLA_API_KEY`

---

## License

Portfolio/demonstration project. Not intended for redistribution.
