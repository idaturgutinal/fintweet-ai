#!/bin/bash
# FinTweet DB Backup - Gunluk fintweet.db yedeklemesi
set -e

DB_SRC="$HOME/.openclaw/workspace/fintweet.db"
BACKUP_DIR="$HOME/.openclaw/backups"
DATE=$(date +%Y-%m-%d)
BACKUP_FILE="$BACKUP_DIR/fintweet_${DATE}.db"

if [ ! -f "$DB_SRC" ]; then
    echo "[HATA] DB bulunamadi: $DB_SRC" >&2
    exit 1
fi

cp "$DB_SRC" "$BACKUP_FILE"
echo "[OK] Backup alindi: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# 7 gunden eski yedekleri sil
DELETED=$(find "$BACKUP_DIR" -name "fintweet_*.db" -mtime +7 -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[OK] $DELETED eski yedek silindi"
fi
