#!/usr/bin/env bash
# Respaldo diario de PostgreSQL. Cron sugerido (3:30 AM): 30 3 * * * /ruta/a/Angsidex/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

file="$BACKUP_DIR/angside_$(date +%F_%H%M).sql.gz"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$file"
test -s "$file" || { echo "Respaldo vacío: $file" >&2; rm -f "$file"; exit 1; }
chmod 600 "$file"
find "$BACKUP_DIR" -name 'angside_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "Respaldo creado: $file"
