"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SERVICE 2 – Price History & Prédiction  (port 8002)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ROUTES
  GET  /products/{id}/price-history   → timeline 30j + changements
  GET  /products/{id}/price-stats     → stats agrégées (min/max/moy)
  GET  /products/{id}/prediction      → prédiction IA (régression linéaire)
  GET  /price-changes                 → derniers changements globaux
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import logging
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app import crud, schemas
from app.models import Product

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Service 2 – Price History & Prédiction",
    description=(
        "Microservice responsable de l'**historique des prix** et de la **prédiction IA**.\n\n"
        "Ce service lit la base partagée (price_daily, price_history) créée par le Service 1.\n\n"
        "**Routes principales :**\n"
        "- `GET /products/{id}/price-history` — timeline 30 jours + changements\n"
        "- `GET /products/{id}/price-stats` — statistiques agrégées\n"
        "- `GET /products/{id}/prediction` — prédiction par régression linéaire\n"
        "- `GET /price-changes` — flux global des derniers changements\n\n"
        "Port : **8002**"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    logger.info("Service 2 – Price History & Prédiction démarré")
    init_db()


# ── Santé ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Général"])
def health_check(db: Session = Depends(get_db)):
    import os, re
    from sqlalchemy import text
    try:
        total_products = db.execute(text("SELECT COUNT(*) FROM products")).scalar()
        total_daily    = db.execute(text("SELECT COUNT(*) FROM price_daily")).scalar()
        total_history  = db.execute(text("SELECT COUNT(*) FROM price_history")).scalar()
        db_url = os.getenv("DATABASE_URL", "non defini — utilise localhost par defaut")
        db_url = re.sub(r":([^@]+)@", ":***@", db_url)
        return {
            "status": "ok", "service": "price-history", "port": 8002,
            "database_url":   db_url,
            "total_products": total_products,
            "total_daily":    total_daily,
            "total_history":  total_history,
        }
    except Exception as e:
        return {"status": "error", "service": "price-history", "detail": str(e),
                "fix": "Verifiez DATABASE_URL dans votre .env"}


# ── Historique des prix ────────────────────────────────────────────────────────

@app.get(
    "/products/{product_id}/price-history",
    response_model=schemas.PriceHistoryResponse,
    tags=["Historique"],
    summary="Timeline 30 jours + changements de prix",
)
def get_price_history(product_id: int, db: Session = Depends(get_db)):
    """
    Retourne :
    - **timeline** : 30 points quotidiens (courbe continue, prix propagé si pas de scraping)
    - **historique** : détail de chaque changement de prix sur 30 jours
    """
    result = crud.get_price_history_full(db, product_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Produit {product_id} introuvable.")
    return result


@app.get(
    "/products/{product_id}/price-stats",
    response_model=schemas.PriceStatsResponse,
    tags=["Historique"],
    summary="Statistiques agrégées sur les prix",
)
def get_price_stats(product_id: int, db: Session = Depends(get_db)):
    """
    Retourne : prix min, max, moyen, nombre de jours suivis,
    nombre de changements et variation en %.
    """
    result = crud.get_price_stats(db, product_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Produit {product_id} introuvable ou pas encore de données de prix.",
        )
    return result


# ── Prédiction ─────────────────────────────────────────────────────────────────

@app.get(
    "/products/{product_id}/prediction",
    response_model=schemas.PredictionResponse,
    tags=["Prédiction"],
    summary="Prédire le prix futur d'un produit (IA – Régression Linéaire)",
)
def get_price_prediction(
    product_id: int,
    days: int = Query(15, ge=2, le=30, description="Nombre de jours dans le futur (2–30)"),
    db: Session = Depends(get_db),
):
    """
    Utilise une **régression linéaire** sur l'historique `price_daily`
    pour estimer le prix futur.

    - **days** : horizon de prédiction (2 à 30 jours)
    - **trend** : `up` (hausse), `down` (baisse), `stable`
    - Nécessite au moins **2 jours** de données historiques.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable.")

    prediction_data = crud.predict_product_price(db, product_id, days)
    if not prediction_data:
        raise HTTPException(
            status_code=400,
            detail="Pas assez de données historiques (minimum 2 jours de prix requis).",
        )

    logger.info(f"[prediction] product_id={product_id} days={days} → {prediction_data['predicted_price']}")
    return {"product_id": product_id, **prediction_data}


# ── Flux global des changements ────────────────────────────────────────────────

@app.get(
    "/price-changes",
    response_model=List[schemas.PriceChangeItem],
    tags=["Historique"],
    summary="Derniers changements de prix (toutes boutiques)",
)
def get_price_changes(
    product_id: Optional[int] = Query(None, description="Filtrer par produit"),
    boutique:   Optional[str] = Query(None, description="Filtrer par boutique"),
    limit:      int           = Query(50, ge=1, le=200),
    db:         Session       = Depends(get_db),
):
    """
    Flux des derniers changements de prix, triés du plus récent au plus ancien.
    Utile pour un dashboard de monitoring ou un feed en temps réel.
    """
    return crud.get_all_price_changes(db, product_id=product_id, boutique=boutique, limit=limit)



# ── Recherche de produits (Utilisé par ComparePage) ────────────────────────────

# ── Recherche de produits (Utilisé par ComparePage) ────────────────────────────

@app.get(
    "/products/search",
    tags=["Recherche"],
    summary="Rechercher un produit par nom (Pour correspondance ID)",
)
def search_products(
    q: str = Query(..., description="Nom du produit à rechercher"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """
    Recherche un produit dans la base de données locale.
    Adaptée pour correspondre à la structure de données du Service 3 (Alertes).
    """
    # Recherche insensible à la casse dans le nom du produit
    query = db.query(Product).filter(
        Product.name.ilike(f"%{q}%") | Product.nom.ilike(f"%{q}%") # Cherche dans 'name' OU 'nom'
    ).limit(limit)
    
    results = query.all()
    
    # Formatage robuste des résultats pour correspondre à l'attente du frontend
    formatted_results = []
    for p in results:
        # On essaie de récupérer le nom soit depuis 'nom' (Service 3) soit 'name' (Standard)
        p_nom = getattr(p, "nom", None) or getattr(p, "name", "")
        # Idem pour le lien/URL
        p_lien = getattr(p, "lien", None) or getattr(p, "url", "")
        # Idem pour la boutique
        p_boutique = getattr(p, "boutique", None) or getattr(p, "source", "")

        formatted_results.append({
            "id": p.id,
            "nom": p_nom,
            "boutique": p_boutique,
            "lien": p_lien,
            "prix": getattr(p, "prix_num", 0) or getattr(p, "current_price", 0)
        })
        
    return { "data": formatted_results }

import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)) # 8000 sera le fallback en local
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)