"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SERVICE 3 – Alertes de Prix  (port 8003)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ROUTES
  POST   /alerts                 → créer une alerte
  GET    /alerts                 → lister les alertes
  GET    /alerts/{id}            → détail d'une alerte
  DELETE /alerts/{id}            → supprimer une alerte
  PATCH  /alerts/{id}/deactivate → désactiver une alerte
  POST   /alerts/verify          → vérifier toutes les alertes actives
  GET    /alerts/stats           → statistiques des alertes

  SCHEDULER (automatique)
  └─ Vérification des alertes toutes les heures (configurable via ALERT_CHECK_HOUR)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import logging
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, init_db, SessionLocal
from app import crud, schemas
from app.models import Product
from app.email_service import envoyer_confirmation_alerte

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Service 3 – Alertes de Prix",
    description=(
        "Microservice responsable de la **gestion et l'envoi des alertes de prix**.\n\n"
        "**Logique :**\n"
        "1. L'utilisateur crée une alerte avec un `product_id` et un `prix_cible`.\n"
        "2. Le scheduler vérifie périodiquement si `prix_actuel ≤ prix_cible`.\n"
        "3. Si oui → email envoyé + alerte désactivée automatiquement.\n\n"
        "**Configuration email** (variables .env) :\n"
        "- `GMAIL_USER` : adresse Gmail expéditrice\n"
        "- `GMAIL_APP_PASSWORD` : mot de passe d'application Gmail\n\n"
        "Port : **8003**"
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
    logger.info("Service 3 – Alertes de Prix démarré")
    init_db()
    _start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler arrêté")


# ── Scheduler ──────────────────────────────────────────────────────────────────

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

def _start_scheduler():
    check_hour   = int(os.getenv("ALERT_CHECK_HOUR", "3"))
    check_minute = int(os.getenv("ALERT_CHECK_MINUTE", "30"))

    def job_verifier():
        db = SessionLocal()
        try:
            rapport = crud.verifier_alertes(db)
            logger.info(f"[scheduler] Alertes : {rapport}")
        finally:
            db.close()

    scheduler.add_job(
        func=job_verifier,
        trigger="cron",
        hour=check_hour,
        minute=check_minute,
        id="check_alerts",
    )
    scheduler.start()
    logger.info(f"[scheduler] Vérification alertes planifiée à {check_hour:02d}:{check_minute:02d}")


# ── Santé ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Général"])
def health_check(db: Session = Depends(get_db)):
    import os, re
    from sqlalchemy import text
    try:
        total_products = db.execute(text("SELECT COUNT(*) FROM products")).scalar()
        total_alerts   = db.execute(text("SELECT COUNT(*) FROM alerts")).scalar()
        db_url = os.getenv("DATABASE_URL", "non defini — utilise localhost par defaut")
        db_url = re.sub(r":([^@]+)@", ":***@", db_url)
        return {
            "status": "ok", "service": "alerts", "port": 8003,
            "database_url":   db_url,
            "total_products": total_products,
            "total_alerts":   total_alerts,
        }
    except Exception as e:
        return {"status": "error", "service": "alerts", "detail": str(e),
                "fix": "Verifiez DATABASE_URL dans votre .env"}


# ── CRUD Alertes ───────────────────────────────────────────────────────────────

# ── CRUD Alertes ───────────────────────────────────────────────────────────────

# ── CRUD Alertes ───────────────────────────────────────────────────────────────

# EN HAUT DE main.py, AJOUTE BackgroundTasks :
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks

# ...

# REMPLACE L'ANCIENNE FONCTION creer_alerte PAR CELLE-CI :
@app.post(
    "/alerts",
    response_model=schemas.AlertResponse,
    status_code=201,
    tags=["Alertes"],
    summary="Créer une alerte de prix",
)
def creer_alerte(body: schemas.AlertCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Crée une alerte et envoie l'email de confirmation en arrière-plan.
    L'API répond instantanément au frontend.
    """
    # 1. Récupérer le produit depuis la DB
    produit = db.query(Product).filter(Product.id == body.product_id).first()
    
    if not produit:
        raise HTTPException(
            status_code=404,
            detail=f"Produit {body.product_id} introuvable dans la base de données.",
        )

    # 2. Logique de sélection du prix CORRECT
    final_prix_actuel = produit.prix_num
    
    # HEURISTIQUE DE CORRECTION :
    if (final_prix_actuel is None or final_prix_actuel < 2) and (body.prix_actuel and body.prix_actuel > 2):
        logger.warning(f"[alerts] Correction Prix: DB={final_prix_actuel} -> Frontend={body.prix_actuel} (Produit ID {body.product_id})")
        final_prix_actuel = body.prix_actuel

    # 3. Compléter les infos nom/URL si vides
    product_name = body.product_name
    product_url  = body.product_url
    
    if not product_name:
        product_name = produit.nom
    if not product_url:
        product_url = produit.lien or ""

    # 4. Créer l'alerte en BDD
    alerte = crud.creer_alerte(
        db,
        user_id      = body.user_id,
        user_email   = body.user_email,
        product_id   = body.product_id,
        prix_cible   = body.prix_cible,
        prix_actuel  = final_prix_actuel,
        product_name = product_name,
        product_url  = product_url,
    )

    # 5. Email de confirmation EN TÂCHE DE FOND (NON BLOQUANT)
    background_tasks.add_task(
        envoyer_confirmation_alerte,
        destinataire = body.user_email,
        product_name = product_name,
        product_url  = product_url,
        prix_actuel  = final_prix_actuel or 0.0,
        prix_cible   = body.prix_cible,
        alerte_id    = alerte.id,
    )

    # 6. On retourne l'alerte IMMÉDIATEMENT au frontend (avant même que l'email soit parti)
    return alerte


@app.get(
    "/alerts",
    response_model=List[schemas.AlertResponse],
    tags=["Alertes"],
    summary="Lister les alertes",
)
def list_alertes(
    user_id:     Optional[str] = Query(None, description="Filtrer par utilisateur"),
    product_id:  Optional[int] = Query(None, description="Filtrer par produit"),
    active_only: bool          = Query(False, description="Uniquement les alertes actives"),
    limit:       int           = Query(50, ge=1, le=200),
    db:          Session       = Depends(get_db),
):
    return crud.get_alertes(db, user_id=user_id, product_id=product_id,
                            active_only=active_only, limit=limit)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "alerts"}
@app.get(
    "/alerts/stats",
    response_model=schemas.AlertStats,
    tags=["Alertes"],
    summary="Statistiques des alertes",
)
def get_stats(db: Session = Depends(get_db)):
    """Retourne total, actives, déclenchées et expirées."""
    return crud.get_alertes_stats(db)


@app.get(
    "/alerts/{alerte_id}",
    response_model=schemas.AlertResponse,
    tags=["Alertes"],
    summary="Détail d'une alerte",
)
def get_alerte(alerte_id: int, db: Session = Depends(get_db)):
    alerte = crud.get_alerte_by_id(db, alerte_id)
    if not alerte:
        raise HTTPException(status_code=404, detail=f"Alerte {alerte_id} introuvable.")
    return alerte


@app.patch(
    "/alerts/{alerte_id}/deactivate",
    tags=["Alertes"],
    summary="Désactiver une alerte",
)
def desactiver_alerte(alerte_id: int, db: Session = Depends(get_db)):
    """Désactive manuellement une alerte (sans supprimer)."""
    if not crud.desactiver_alerte(db, alerte_id):
        raise HTTPException(status_code=404, detail=f"Alerte {alerte_id} introuvable.")
    return {"message": f"Alerte {alerte_id} désactivée.", "alerte_id": alerte_id}


@app.delete(
    "/alerts/{alerte_id}",
    tags=["Alertes"],
    summary="Supprimer une alerte",
)
def supprimer_alerte(alerte_id: int, db: Session = Depends(get_db)):
    """⚠️ Supprime définitivement une alerte."""
    if not crud.supprimer_alerte(db, alerte_id):
        raise HTTPException(status_code=404, detail=f"Alerte {alerte_id} introuvable.")
    return {"message": f"Alerte {alerte_id} supprimée.", "alerte_id": alerte_id}


# ── Vérification manuelle ──────────────────────────────────────────────────────

@app.post(
    "/alerts/verify",
    response_model=schemas.AlertVerifyReport,
    tags=["Alertes"],
    summary="Déclencher la vérification des alertes maintenant",
)
def verifier_alertes_maintenant(db: Session = Depends(get_db)):
    """
    Lance immédiatement la vérification de toutes les alertes actives.
    Utile pour tester ou forcer une vérification après un scraping.

    **Normalement** cette vérification est faite automatiquement par le scheduler
    configuré via `ALERT_CHECK_HOUR` et `ALERT_CHECK_MINUTE` dans `.env`.
    """
    rapport = crud.verifier_alertes(db)
    logger.info(f"[API] Vérification manuelle : {rapport}")
    return rapport



# ── CRUD Favoris ───────────────────────────────────────────────────────────────
@app.post(
    "/favorites",
    response_model=schemas.FavoriteResponse,
    status_code=201,
    tags=["Favoris"],
    summary="Ajouter un produit aux favoris",
)
def ajouter_aux_favoris(body: schemas.FavoriteCreate, db: Session = Depends(get_db)):
    """Ajoute un produit en favori. Si déjà présent, retourne le favori existant."""
    return crud.ajouter_favori(db, fav_data=body)


@app.get(
    "/favorites",
    response_model=List[schemas.FavoriteResponse],
    tags=["Favoris"],
    summary="Lister les favoris d'un utilisateur",
)
def lister_favoris(
    user_id: str = Query(..., description="ID de l'utilisateur"),
    db: Session = Depends(get_db),
):
    return crud.get_favoris(db, user_id=user_id)


@app.delete(
    "/favorites/{favori_id}",
    tags=["Favoris"],
    summary="Supprimer un favori",
)
def supprimer_des_favoris(favori_id: int, db: Session = Depends(get_db)):
    """⚠️ Supprime un produit de la liste des favoris."""
    if not crud.supprimer_favori(db, favori_id):
        raise HTTPException(status_code=404, detail=f"Favori {favori_id} introuvable.")
    return {"message": f"Favori {favori_id} supprimé.", "favori_id": favori_id}

import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)) # 8000 sera le fallback en local
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)