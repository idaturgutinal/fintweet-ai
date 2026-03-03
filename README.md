# FinTweet AI

**Autonomous financial content pipeline for Turkish crypto/finance Twitter (@equinoxistr).**

FinTweet AI scans news sources, generates tweet drafts using LLMs, validates them for grammar and accuracy, routes them through a Telegram approval workflow, and publishes to Twitter — all running 24/7 on a Hetzner VPS.

---

## System Architecture

```
                     ┌─────────────────────────────────────────┐
                     │            CRON SCHEDULER               │
                     │  (6 scanner slots + 8 xpatla slots)     │
                     └──────────┬──────────┬───────────────────┘
                                │          │
                     ┌──────────▼──┐  ┌───▼────────────┐
                     │  SCANNER    │  │  AUTO XPATLA   │
                     │             │  │                 │
                     │ Brave Search│  │ Claude API      │
                     │ Twitter API │  │ Dedup (>60%)    │
                     │ RSS Feeds   │  │ SOUL.md Persona │
                     └──────┬──────┘  └───────┬─────────┘
                            │                 │
                            ▼                 ▼
                     ┌──────────────────────────────┐
                     │        FINTWEET.DB           │
                     │                              │
                     │  findings     scan_log       │
                     │  tweets       engagement     │
                     │  suggestions  xpatla_log     │
                     └──────────────┬───────────────┘
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │      TWEET VALIDATOR         │
                     │      (Claude Haiku)          │
                     │                              │
                     │  ✓ Turkish grammar           │
                     │  ✓ Foreign word suffixes     │
                     │  ✓ Content accuracy (>=70)   │
                     └──────────────┬───────────────┘
                                    │
                           ┌────────┴────────┐
                           │                 │
                     accuracy < 70     accuracy >= 70
                           │                 │
                           ▼                 ▼
                     ┌──────────┐   ┌───────────────┐
                     │ REJECTED │   │ TELEGRAM BOT  │
                     │ (logged) │   │               │
                     └──────────┘   │ ✅ Onayla      │
                                    │ ❌ Reddet      │
                                    │ ✏️ Düzenle     │
                                    │ 💬 Quote       │
                                    └───────┬───────┘
                                            │
                                 ┌──────────┴──────────┐
                                 │                     │
                           score >= 75           score < 75
                                 │                     │
                                 ▼                     ▼
                     ┌─────────────────┐    ┌──────────────┐
                     │  AUTO-APPROVE   │    │ MANUAL WAIT  │
                     │                 │    │ (Telegram)   │
                     │ Priority:       │    └──────────────┘
                     │ 1. Quote tweet  │
                     │ 2. High score   │
                     │ 3. Fresh news   │
                     │                 │
                     │ Max 1 per run   │
                     │ Cooldown 45-90m │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │  TWEET.PY       │
                     │  (Publisher)     │
                     │                 │
                     │ OAuth 1.0a      │
                     │ Tweet / Quote   │
                     │ 403 Fallback    │
                     └────────┬────────┘
                              │
                     ┌────────┴────────┐
                     │                 │
               quote OK          quote 403
                     │                 │
                     ▼                 ▼
               ┌──────────┐   ┌──────────────┐
               │ QUOTE    │   │ FALLBACK     │
               │ TWEET    │   │ Tweet + Link │
               └──────────┘   └──────────────┘
                     │                 │
                     └────────┬────────┘
                              ▼
                     ┌─────────────────┐
                     │   TWITTER       │
                     │  @equinoxistr   │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │  ENGAGEMENT     │
                     │  TRACKER        │
                     │  (every 2h)     │
                     └─────────────────┘
```

---

## Pipeline Deep Dive

### 1. Scanner

News collection engine running 6 times daily.

```
Sources:
├── Brave Search API ──── 20 categories, ~61 queries
├── Twitter API v2 ────── 17 categories, ~255 accounts
└── RSS Feeds ─────────── Financial news feeds

Output: findings table (scored & deduplicated)
```

Categories tracked: Bitcoin, Ethereum, DeFi, altcoins, stablecoins, ETF flows, whale movements, on-chain data, macro economics, Turkey economy, regulation, US markets, geopolitics, AI/tech.

### 2. Tweet Generation

8 time slots, each targeting specific content categories:

```
┌────────────────────┬───────┬───────┬──────────────────────────────────┐
│       Slot         │  UTC  │  TR   │          Categories              │
├────────────────────┼───────┼───────┼──────────────────────────────────┤
│ morning_macro      │ 04:30 │ 07:30 │ Macro, breaking, Turkey          │
│ crypto_analysis    │ 06:00 │ 09:00 │ Crypto analysis, ETF             │
│ breaking_onchain   │ 08:00 │ 11:00 │ Breaking, on-chain, whale        │
│ turkey_regulation  │ 10:30 │ 13:30 │ Turkish economy, regulation      │
│ defi_altcoin       │ 12:00 │ 15:00 │ DeFi, altcoin, stablecoin        │
│ us_market_open     │ 13:30 │ 16:30 │ US markets, macro                │
│ whale_social       │ 16:30 │ 19:30 │ Whale alerts, social signals     │
│ night_global       │ 19:00 │ 22:00 │ Geopolitics, AI, science         │
└────────────────────┴───────┴───────┴──────────────────────────────────┘
```

### 3. Tweet Validator

Every generated tweet passes through a 3-layer quality gate via Claude Haiku:

```
Layer 1: GRAMMAR
├── Turkish spelling & grammar
├── Punctuation, capitalization
└── Natural, fluent Turkish

Layer 2: FOREIGN WORD SUFFIXES
├── Suffixes follow PRONUNCIATION, not spelling
├── Bitcoin'in (not Bitcoin'ın) — "bitkoin" → ince
├── Ethereum'un (not Ethereum'ün) — "itıryum" → kalın
├── Trump'ın (not Trump'in) — "tramp" → kalın
├── ETF'in — "ef" → ince
├── DeFi'nin — "difay" → kalın
└── Apostrophe required: Bitcoin'e, Solana'dan

Layer 3: CONTENT ACCURACY
├── Compare tweet claims vs source article
├── Verify numbers, dates, names
├── Flag fabricated claims
└── accuracy_score (0-100), reject if < 70
```

### 4. Smart Auto-Approve

```
All candidates (score >= 75)
          │
          ▼
┌─────────────────────┐
│   PRIORITY SORT     │
│                     │
│ 1. Has source tweet │── Quote tweets first
│ 2. Highest score    │── Best content
│ 3. Freshest news    │── Most timely
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  COOLDOWN CHECK     │
│                     │
│ Last auto-approve   │
│ + random(45-90 min) │
│ = next allowed time │
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    │           │
 cooldown    cooldown
 passed      active
    │           │
    ▼           ▼
  AUTO       SEND TO
  APPROVE    TELEGRAM
  (max 1)    (manual)
```

### 5. Quote Tweet 403 Fallback

```
quote_tweet(text, source_id)
          │
          ▼
      Twitter API
          │
    ┌─────┴─────┐
    │           │
  200 OK    403 Forbidden
    │       "Quoting not allowed"
    │           │
    ▼           ▼
  Quote     Fallback:
  Posted    tweet(text + source_link)
```

---

## Monitoring & Alerts

```
┌────────────────────┬──────────────────┬────────────────────────────┐
│     Component      │     Schedule     │         Function           │
├────────────────────┼──────────────────┼────────────────────────────┤
│ alert_monitor.py   │ 24/7 (60s loop)  │ Price spikes, whale moves  │
│ engagement_tracker │ Every 2h (07-19) │ Likes, RTs, replies, views │
│ morning_summary    │ Daily 07:15 TR   │ Market summary tweet       │
│ weekly_report      │ Sunday 20:00 TR  │ Performance report         │
│ optimizer          │ 1st of month     │ Strategy optimization      │
│ error_notifier     │ On exception     │ Telegram error alerts      │
│ db_backup.sh       │ Daily 05:00 TR   │ SQLite backup (7-day)      │
│ logrotate          │ Daily 05:30 TR   │ Log rotation               │
└────────────────────┴──────────────────┴────────────────────────────┘
```

---

## Database Schema

```
fintweet.db
├── findings ─────────── Crawled news items with relevance scores
├── scan_log ─────────── Scanner execution history & stats
├── twitter_cache ────── Twitter API response cache
├── auto_xpatla_log ──── Tweet generation run history
├── xpatla_generations ─ LLM API call records & responses
├── telegram_suggestions Draft tweets sent to Telegram
├── tweets ───────────── Published tweets with metadata
├── tweet_engagement ─── Per-tweet metrics over time
└── api_usage ────────── API call tracking & costs
```

---

## File Structure

```
fintweet-ai/
│
├── Core Pipeline
│   ├── scanner.py              # News crawler (Brave + Twitter + RSS)
│   ├── auto_xpatla.py          # Tweet generator + auto-approve + cooldown
│   ├── tweet_validator.py      # 3-layer quality gate
│   ├── telegram_bot.py         # Long-polling Telegram bot (24/7)
│   ├── telegram_commands.py    # Command handler
│   ├── tweet.py                # Twitter publisher (403 fallback)
│   └── xpatla.py               # Claude/XPatla API integration
│
├── Monitoring & Reports
│   ├── alert_monitor.py        # 24/7 price/whale alert daemon
│   ├── engagement_tracker.py   # Tweet metrics collector
│   ├── morning_summary.py      # Daily market summary
│   ├── weekly_report.py        # Weekly performance report
│   └── optimizer.py            # Monthly strategy optimization
│
├── Utilities
│   ├── thread.py               # Reply chain utility
│   ├── twitter_reader.py       # Twitter account reader
│   ├── update_sources.py       # Source config updater
│   ├── error_notifier.py       # Telegram error alerts
│   ├── db_backup.sh            # Daily SQLite backup
│   └── logrotate.conf          # Log rotation config
│
├── Configuration
│   ├── SOUL.md                 # Persona (format/persona/tone)
│   ├── sources.json            # News sources (not in repo)
│   ├── .env                    # API keys (not in repo)
│   └── .env.example            # Environment template
│
└── README.md
```

---

## SOUL Persona Engine

```
Format:    micro | punch | spark | storm | thunder
Persona:   authority | sigma | storyteller | visionary
Tone:      raw | polished | unhinged | deadpan
```

Each tweet uses a random combination for varied, natural-sounding content.

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3 |
| Database | SQLite |
| LLM (Generation) | Claude Sonnet via XPatla API |
| LLM (Validation) | Claude Haiku |
| Social | Twitter API v2 (OAuth 1.0a) |
| Messaging | Telegram Bot API |
| Search | Brave Search API |
| Infrastructure | Hetzner VPS, Ubuntu 24 |
| Scheduling | Cron (26 jobs) |
| Version Control | Git + GitHub |

---

## Cron Schedule Overview

```
Hour (UTC):  01  02  03  04  05  06  07  08  09  10  11  12  13  14  15  16  17  18  19
Scanner:     █               █           █           █           █           █
XPatla:                  █       █       █       █       █   █           █           █
Summary:                 █
Engagement:                          █       █       █       █       █       █       █
Backup:          █
Weekly:                                                                      █(Sun)
```

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

```
TWITTER_API_KEY=         # Twitter OAuth 1.0a
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=
TWITTER_BEARER_TOKEN=    # Twitter API v2 read
TELEGRAM_BOT_TOKEN=      # Telegram bot
TELEGRAM_CHAT_ID=        # Telegram channel ID
BRAVE_API_KEY=           # Brave Search
ANTHROPIC_API_KEY=       # Claude API (validation)
XPATLA_API_KEY=          # XPatla API (generation)
```

---

## License

Portfolio/demonstration project. Not intended for redistribution.

---

Built with Claude API, running on Hetzner VPS.
