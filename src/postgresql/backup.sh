#!/bin/bash
# Backup script for postgresql in docker-compose
# Ensure you are running this from the project root.

set -e

BACKUP_FILE=${1:-"backup_$(date +%Y%m%d_%H%M%S).sql"}

echo "Backing up PostgreSQL database to $BACKUP_FILE..."
# Connect to the running postgresql container and dump the 'otel' database.
# Note: POSTGRES_USER is 'root' by default in docker-compose.yml
docker compose exec -T postgresql pg_dump -U root -d otel > "$BACKUP_FILE"
echo "Backup completed successfully."
