"""
FICHIER: routers/admin.py
ROLE: Routes spécifiques aux administrateurs
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict

import models, auth, schemas
from database import get_db

router = APIRouter(prefix="/admin", tags=["Administration"])

@router.get(
    "/dashboard",
    response_model=Dict[str, Any],
    summary="Tableau de bord administrateur"
)
async def admin_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> Any:
    """
    Tableau de bord avec des statistiques pour les administrateurs.
    
    **Nécessite d'être administrateur.**
    """
    # Statistiques réelles depuis la base de données
    total_users = db.query(models.User).count()
    active_users = db.query(models.User).filter(models.User.is_active == True).count()
    admin_users = db.query(models.User).filter(models.User.is_admin == True).count()
    
    # Utilisateurs créés aujourd'hui
    from datetime import date, timedelta
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    new_users_today = db.query(models.User).filter(
        models.User.created_at >= today,
        models.User.created_at < tomorrow
    ).count()
    
    return {
        "message": f"Bienvenue sur le dashboard admin, {current_user.username}",
        "admin_info": {
            "email": current_user.email,
            "id": current_user.id
        },
        "statistiques": {
            "total_utilisateurs": total_users,
            "utilisateurs_actifs": active_users,
            "administrateurs": admin_users,
            "nouveaux_aujourdhui": new_users_today
        }
    }

@router.get(
    "/users/recent",
    response_model=list[schemas.UserResponse],
    summary="Derniers utilisateurs inscrits"
)
async def recent_users(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> Any:
    """
    Récupère les derniers utilisateurs inscrits.
    
    - **limit**: Nombre d'utilisateurs à retourner (défaut: 10)
    
    **Nécessite d'être administrateur.**
    """
    users = db.query(models.User).order_by(
        models.User.created_at.desc()
    ).limit(limit).all()
    
    return users

@router.get(
    "/stats/activity",
    summary="Statistiques d'activité"
)
async def activity_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> Any:
    """
    Statistiques détaillées sur l'activité des utilisateurs.
    
    **Nécessite d'être administrateur.**
    """
    from datetime import datetime, timedelta
    
    # Périodes
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    # Statistiques
    stats = {
        "total": db.query(models.User).count(),
        "cette_semaine": db.query(models.User).filter(
            models.User.created_at >= week_ago
        ).count(),
        "ce_mois": db.query(models.User).filter(
            models.User.created_at >= month_ago
        ).count(),
        "par_provider": {
            "local": db.query(models.User).filter(
                models.User.auth_provider == "local"
            ).count(),
            "google": db.query(models.User).filter(
                models.User.auth_provider == "google"
            ).count()
        }
    }
    
    return stats