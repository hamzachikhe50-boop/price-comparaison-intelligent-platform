"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  crud.py – Service 2 : Price History & Prédiction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import date, timedelta, datetime

import numpy as np
from sklearn.linear_model import LinearRegression

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models import Product, PriceHistory, PriceDaily

logger = logging.getLogger(__name__)


# ─── Historique des prix ───────────────────────────────────────────────────────

def get_price_history_full(db: Session, product_id: int) -> Optional[Dict[str, Any]]:
    """
    Retourne la timeline 30 jours + les changements de prix détaillés.
    """
    produit = db.query(Product).filter(Product.id == product_id).first()
    if not produit:
        return None

    aujourd_hui = date.today()
    debut       = aujourd_hui - timedelta(days=29)

    # Prix daily sur 30 jours
    daily_rows = (
        db.query(PriceDaily)
        .filter(
            PriceDaily.product_id == product_id,
            PriceDaily.jour >= debut,
            PriceDaily.jour <= aujourd_hui,
        )
        .order_by(PriceDaily.jour.asc())
        .all()
    )

    # Changements sur 30 jours
    changements = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.product_id == product_id,
            func.date(PriceHistory.scrape_date) >= debut,
        )
        .all()
    )

    jours_avec_changement = {ph.scrape_date.date() for ph in changements}
    prix_par_jour = {row.jour: row for row in daily_rows}

    # Construire la timeline continue
    timeline = []
    dernier_prix_connu = None
    dernier_prix_txt   = None

    for i in range(30):
        jour = debut + timedelta(days=i)
        row  = prix_par_jour.get(jour)

        if row:
            dernier_prix_connu = row.prix_num
            dernier_prix_txt   = row.prix_txt

        if dernier_prix_connu is not None:
            timeline.append({
                "jour":            jour.isoformat(),
                "prix_num":        dernier_prix_connu,
                "prix_txt":        dernier_prix_txt,
                "scrape_effectue": row is not None,
                "prix_change":     jour in jours_avec_changement,
            })

    # Détails des changements
    historique_details = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.product_id == product_id,
            func.date(PriceHistory.scrape_date) >= debut,
        )
        .order_by(PriceHistory.scrape_date.desc())
        .all()
    )

    return {
        "product_id":    product_id,
        "nom":           produit.nom,
        "boutique":      produit.boutique,
        "prix_actuel":   produit.prix,
        "total_changes": len(historique_details),
        "timeline":      timeline,
        "historique": [
            {
                "id":               h.id,
                "product_id":       h.product_id,
                "ancien_prix":      h.ancien_prix,
                "nouveau_prix":     h.nouveau_prix,
                "ancien_prix_txt":  h.ancien_prix_txt,
                "nouveau_prix_txt": h.nouveau_prix_txt,
                "scrape_date":      h.scrape_date.isoformat(),
            }
            for h in historique_details
        ],
    }


def get_price_stats(db: Session, product_id: int) -> Optional[Dict[str, Any]]:
    """
    Statistiques agrégées sur les prix d'un produit :
    min, max, moyenne, variation, nombre de changements.
    """
    produit = db.query(Product).filter(Product.id == product_id).first()
    if not produit:
        return None

    stats = (
        db.query(
            func.min(PriceDaily.prix_num).label("prix_min"),
            func.max(PriceDaily.prix_num).label("prix_max"),
            func.avg(PriceDaily.prix_num).label("prix_moyen"),
            func.count(PriceDaily.id).label("nb_jours"),
        )
        .filter(PriceDaily.product_id == product_id)
        .first()
    )

    nb_changements = (
        db.query(func.count(PriceHistory.id))
        .filter(PriceHistory.product_id == product_id)
        .scalar()
    )

    if not stats or stats.nb_jours == 0:
        return None

    variation = None
    if stats.prix_min and stats.prix_max and stats.prix_min > 0:
        variation = round(((stats.prix_max - stats.prix_min) / stats.prix_min) * 100, 2)

    return {
        "product_id":      product_id,
        "nom":             produit.nom,
        "boutique":        produit.boutique,
        "prix_actuel":     produit.prix_num,
        "prix_min":        round(stats.prix_min, 3)   if stats.prix_min   else None,
        "prix_max":        round(stats.prix_max, 3)   if stats.prix_max   else None,
        "prix_moyen":      round(stats.prix_moyen, 3) if stats.prix_moyen else None,
        "nb_jours_suivi":  stats.nb_jours,
        "nb_changements":  nb_changements,
        "variation_pct":   variation,
    }


def get_all_price_changes(
    db: Session,
    product_id: Optional[int] = None,
    boutique: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Retourne les derniers changements de prix, toutes boutiques ou pour un produit.
    """
    query = db.query(PriceHistory, Product).join(Product, PriceHistory.product_id == Product.id)

    if product_id:
        query = query.filter(PriceHistory.product_id == product_id)
    if boutique:
        query = query.filter(Product.boutique.ilike(f"%{boutique}%"))

    rows = query.order_by(desc(PriceHistory.scrape_date)).limit(limit).all()

    return [
        {
            "id":               h.id,
            "product_id":       h.product_id,
            "nom":              p.nom,
            "boutique":         p.boutique,
            "lien":             p.lien,
            "ancien_prix":      h.ancien_prix,
            "nouveau_prix":     h.nouveau_prix,
            "ancien_prix_txt":  h.ancien_prix_txt,
            "nouveau_prix_txt": h.nouveau_prix_txt,
            "scrape_date":      h.scrape_date.isoformat(),
        }
        for h, p in rows
    ]


# ─── Prédiction ────────────────────────────────────────────────────────────────

def predict_product_price(
    db: Session,
    product_id: int,
    days_ahead: int
) -> Optional[Dict[str, Any]]:
    """
    Prédit le prix dans X jours via régression linéaire sur PriceDaily.
    Requiert au moins 2 jours de données.
    """
    history = (
        db.query(PriceDaily)
        .filter(PriceDaily.product_id == product_id)
        .filter(PriceDaily.prix_num.isnot(None))
        .order_by(PriceDaily.jour.asc())
        .all()
    )

    if len(history) < 2:
        return None

    X = np.array([[row.jour.toordinal()] for row in history])
    y = np.array([row.prix_num for row in history])

    try:
        model = LinearRegression()
        model.fit(X, y)

        last_date      = history[-1].jour
        future_date    = last_date + timedelta(days=days_ahead)
        predicted_price = model.predict([[future_date.toordinal()]])[0]
        current_price  = history[-1].prix_num

        if predicted_price > current_price + 0.01:
            trend = "up"
        elif predicted_price < current_price - 0.01:
            trend = "down"
        else:
            trend = "stable"

        return {
            "current_price":   current_price,
            "predicted_price": round(predicted_price, 3),
            "days_ahead":      days_ahead,
            "prediction_date": future_date.isoformat(),
            "trend":           trend,
        }
    except Exception as e:
        logger.error(f"[crud] Erreur prédiction product {product_id} : {e}")
        return None
