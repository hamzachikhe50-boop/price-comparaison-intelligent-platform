"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  crud.py – Service 3 : Alertes de prix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import Alert, Product ,Favorite
from app.email_service import envoyer_alerte_prix
from app.schemas import FavoriteCreate
logger = logging.getLogger(__name__)


# ─── Créer une alerte ─────────────────────────────────────────────────────────

def creer_alerte(
    db: Session,
    user_id:      str,
    user_email:   str,
    product_id:   int,
    prix_cible:   float,
    prix_actuel:  Optional[float] = None,
    product_name: str = "",
    product_url:  str = "",
) -> Alert:
    alerte = Alert(
        user_id      = user_id,
        user_email   = user_email,
        product_id   = product_id,
        product_name = product_name,
        product_url  = product_url,
        prix_cible   = prix_cible,
        prix_actuel  = prix_actuel,
    )
    db.add(alerte)
    db.commit()
    db.refresh(alerte)
    logger.info(f"[alerts] Alerte créée id={alerte.id} user={user_id} product={product_id} cible={prix_cible}")
    return alerte


# ─── Lister les alertes ───────────────────────────────────────────────────────

def get_alertes(
    db: Session,
    user_id:     Optional[str] = None,
    product_id:  Optional[int] = None,
    active_only: bool          = False,
    limit:       int           = 50,
) -> List[Alert]:
    q = db.query(Alert)
    if user_id:
        q = q.filter(Alert.user_id == user_id)
    if product_id:
        q = q.filter(Alert.product_id == product_id)
    if active_only:
        q = q.filter(Alert.active == True)
    return q.order_by(desc(Alert.created_at)).limit(limit).all()


def get_alerte_by_id(db: Session, alerte_id: int) -> Optional[Alert]:
    return db.query(Alert).filter(Alert.id == alerte_id).first()


# ─── Désactiver / supprimer ───────────────────────────────────────────────────

def desactiver_alerte(db: Session, alerte_id: int) -> bool:
    alerte = db.query(Alert).filter(Alert.id == alerte_id).first()
    if not alerte:
        return False
    alerte.active = False
    db.commit()
    return True


def supprimer_alerte(db: Session, alerte_id: int) -> bool:
    alerte = db.query(Alert).filter(Alert.id == alerte_id).first()
    if not alerte:
        return False
    db.delete(alerte)
    db.commit()
    return True


# ─── Vérification des alertes ─────────────────────────────────────────────────

# ─── Vérification des alertes ─────────────────────────────────────────────────

def verifier_alertes(db: Session) -> Dict[str, Any]:
    """
    Vérifie toutes les alertes actives.
    Priorité : Utilise toujours le prix le plus récent de la DB.
    Si prix_actuel <= prix_cible → envoie email + désactive l'alerte.
    """
    alertes_actives = db.query(Alert).filter(Alert.active == True).all()

    rapport = {
        "total_verifiees": len(alertes_actives),
        "declenchees":     0,
        "emails_envoyes":  0,
        "erreurs":         0,
        "detail":          [],
    }

    if not alertes_actives:
        logger.info("[alerts] Aucune alerte active à vérifier")
        return rapport

    logger.info(f"[alerts] Vérification de {len(alertes_actives)} alertes actives")

    for alerte in alertes_actives:
        produit = db.query(Product).filter(Product.id == alerte.product_id).first()

        if not produit:
            logger.warning(f"[alerts] Produit {alerte.product_id} introuvable pour alerte {alerte.id}")
            rapport["erreurs"] += 1
            continue

        # ── CORRECTION ICI ───────────────────────────────────────────────
        # 1. On prend le prix de la DB en priorité (Source de vérité mise à jour par Service 1)
        prix_actuel = produit.prix_num
        
        # 2. Si la DB n'a pas de prix (NULL), on utilise le prix snapshot stocké dans l'alerte
        if prix_actuel is None:
            prix_actuel = alerte.prix_actuel

        if prix_actuel is None:
            continue

        # Mettre à jour le snapshot dans l'alerte pour le futur (bonne pratique)
        alerte.prix_actuel = prix_actuel
        # ───────────────────────────────────────────────────────────────────

        # ── Condition de déclenchement ────────────────────────────────────
        if prix_actuel <= alerte.prix_cible:
            logger.info(f"[alerts] 🚨 Alerte {alerte.id} déclenchée : {prix_actuel} DT <= {alerte.prix_cible} DT")

            succes = envoyer_alerte_prix(
                destinataire = alerte.user_email,
                product_name = alerte.product_name or produit.nom,
                product_url  = alerte.product_url  or produit.lien or "",
                prix_cible   = alerte.prix_cible,
                prix_actuel  = prix_actuel,
            )

            rapport["declenchees"] += 1
            if succes:
                alerte.active       = False
                alerte.triggered_at = datetime.utcnow()
                rapport["emails_envoyes"] += 1
            else:
                rapport["erreurs"] += 1

            rapport["detail"].append({
                "alerte_id":   alerte.id,
                "product_id":  alerte.product_id,
                "user_email":  alerte.user_email,
                "prix_cible":  alerte.prix_cible,
                "prix_actuel": prix_actuel,
                "email_envoye": succes,
            })

    db.commit()
    logger.info(
        f"[alerts] Vérification terminée : "
        f"{rapport['declenchees']} déclenchées, "
        f"{rapport['emails_envoyes']} emails envoyés, "
        f"{rapport['erreurs']} erreurs"
    )
    return rapport





# ─── Stats ─────────────────────────────────────────────────────────────────────

def get_alertes_stats(db: Session) -> Dict[str, Any]:
    total        = db.query(Alert).count()
    actives      = db.query(Alert).filter(Alert.active == True).count()
    declenchees  = db.query(Alert).filter(Alert.active == False, Alert.triggered_at.isnot(None)).count()

    return {
        "total":       total,
        "actives":     actives,
        "declenchees": declenchees,
        "expirees":    total - actives - declenchees,
    }


# ─── CRUD Favoris ─────────────────────────────────────────────────────────────
def ajouter_favori(db: Session, fav_data: FavoriteCreate):
    # Vérifier si déjà en favori
    existing = db.query(Favorite).filter(
        Favorite.user_id == fav_data.user_id,
        Favorite.product_id == fav_data.product_id
    ).first()
    
    if existing:
        return existing  # Déjà en favori, on le retourne sans erreur
    
    nouveau_favori = Favorite(
        user_id=fav_data.user_id,
        product_id=fav_data.product_id,
        product_name=fav_data.product_name,
        product_url=fav_data.product_url,
        image_url=fav_data.image_url,
        best_price=fav_data.best_price,
        category=fav_data.category
    )
    db.add(nouveau_favori)
    db.commit()
    db.refresh(nouveau_favori)
    return nouveau_favori

def get_favoris(db: Session, user_id: str):
    return db.query(Favorite).filter(Favorite.user_id == user_id).order_by(Favorite.created_at.desc()).all()

def supprimer_favori(db: Session, favori_id: int):
    favori = db.query(Favorite).filter(Favorite.id == favori_id).first()
    if not favori:
        return False
    db.delete(favori)
    db.commit()
    return True