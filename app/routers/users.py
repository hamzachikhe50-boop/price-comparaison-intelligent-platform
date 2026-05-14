"""
FICHIER: routers/users.py
ROLE: Routes pour la gestion des utilisateurs
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Any

import schemas, models, auth
from database import get_db

router = APIRouter(prefix="/users", tags=["Utilisateurs"])

@router.get(
    "/me",
    response_model=schemas.UserResponse,
    summary="Profil de l'utilisateur connecté"
)
async def read_users_me(
    current_user: models.User = Depends(auth.get_current_active_user)
) -> Any:
    """
    Récupère le profil de l'utilisateur actuellement connecté.
    
    Nécessite d'être authentifié.
    """
    return current_user

@router.get(
    "/{user_id}",
    response_model=schemas.UserResponse,
    summary="Récupérer un utilisateur par son ID"
)
async def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> Any:
    """
    Récupère les informations d'un utilisateur spécifique par son ID.
    
    **Nécessite d'être administrateur.**
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    return user

@router.get(
    "/",
    response_model=List[schemas.UserResponse],
    summary="Liste de tous les utilisateurs"
)
async def read_all_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> Any:
    """
    Récupère la liste de tous les utilisateurs avec pagination.
    
    - **skip**: Nombre d'utilisateurs à sauter (pour la pagination)
    - **limit**: Nombre maximum d'utilisateurs à retourner
    
    **Nécessite d'être administrateur.**
    """
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

@router.put(
    "/{user_id}/toggle-admin",
    response_model=schemas.UserResponse,
    summary="Activer/désactiver le rôle admin"
)
async def toggle_admin(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> Any:
    """
    Active ou désactive le rôle administrateur d'un utilisateur.
    
    **Nécessite d'être administrateur.**
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    # Ne pas pouvoir se retirer soit-même les droits admin
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas modifier vos propres droits admin"
        )
    
    # Inverser le statut admin
    user.is_admin = not user.is_admin
    db.commit()
    db.refresh(user)
    
    return user

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un utilisateur"
)
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user)
) -> None:
    """
    Supprime un utilisateur de la base de données.
    
    **Nécessite d'être administrateur.**
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    # Ne pas pouvoir se supprimer soi-même
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous ne pouvez pas supprimer votre propre compte"
        )
    
    db.delete(user)
    db.commit()