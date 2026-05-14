# Tunisia Price Hunter — 3 Microservices

## Démarrage rapide (uvicorn local)

### Prérequis
- Python 3.11+
- PostgreSQL sur localhost:5432
- pip install dans chaque service

### 1. Installer les dépendances

```bash
pip install -r service1-scraping/requirements.txt
pip install -r service2-price/requirements.txt
pip install -r service3-alerts/requirements.txt
```

### 2. Configurer la base de données

Éditer le `.env` dans chaque service si besoin (par défaut : `localhost/scraper_db`) :

```
service1-scraping/.env
service2-price/.env
service3-alerts/.env
```

Contenu par défaut :
```
DATABASE_URL=postgresql://postgres:123456@localhost/scraper_db
```

### 3. Lancer les 3 services

**Option A — Script automatique (recommandé)**
```bash
bash start_local.sh        # démarrer
bash start_local.sh stop   # arrêter
```

**Option B — Manuellement (3 terminaux séparés)**
```bash
# Terminal 1
cd service1-scraping
uvicorn app.main:app --port 8001 --reload

# Terminal 2
cd service2-price
uvicorn app.main:app --port 8002 --reload

# Terminal 3
cd service3-alerts
uvicorn app.main:app --port 8003 --reload
```

---

## Services

| Service | Port | Swagger |
|---------|------|---------|
| Scraping | 8001 | http://localhost:8001/docs |
| Price History & Prédiction | 8002 | http://localhost:8002/docs |
| Alertes | 8003 | http://localhost:8003/docs |

---

## Flux d'utilisation

```bash
# 1. Synchroniser les URLs de catégories
curl -X POST http://localhost:8001/scrape/sync-urls

# 2. Lancer le scraping
curl -X POST http://localhost:8001/scrape/start \
     -H "Content-Type: application/json" \
     -d '{"site": "mytek", "max_pages": 5}'

# 3. Voir les produits
curl http://localhost:8001/products

# 4. Historique des prix d'un produit
curl http://localhost:8002/products/1/price-history

# 5. Prédiction de prix
curl http://localhost:8002/products/1/prediction?days=15

# 6. Créer une alerte
curl -X POST http://localhost:8003/alerts \
     -H "Content-Type: application/json" \
     -d '{"user_id":"u1","user_email":"you@gmail.com","product_id":1,"prix_cible":900.0}'

# 7. Vérifier les alertes manuellement
curl -X POST http://localhost:8003/alerts/verify
```

---

## Diagnostic DB (Service 2 & 3)

Appeler `GET /` sur Service 2 ou 3 affiche l'état de la connexion :
```json
{
  "status": "ok",
  "database_url": "postgresql://postgres:***@localhost/scraper_db",
  "total_products": 1250,
  "total_daily": 3400,
  "total_history": 555
}
```
