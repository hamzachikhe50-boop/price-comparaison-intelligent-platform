#!/bin/bash
# scripts/create_databases.sh
# Créé automatiquement les bases auth_db et scraper_db au premier démarrage

set -e
#postgresuser est défini dans le docker-compose.yml, il est utilisé pour se connecter à PostgreSQL et créer les bases de données
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE auth_db;
    CREATE DATABASE scraper_db;
    GRANT ALL PRIVILEGES ON DATABASE auth_db TO $POSTGRES_USER;
    GRANT ALL PRIVILEGES ON DATABASE scraper_db TO $POSTGRES_USER;
EOSQL

echo "✅ Bases de données auth_db et scraper_db créées."