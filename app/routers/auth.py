"""
FICHIER: routers/auth.py
ROLE: Routes pour l'authentification (inscription, connexion)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Any

import schemas, models, auth
from database import get_db
#APIRouter est pour créer un routeur FastAPI, ici on crée un routeur pour les routes d'authentification
router = APIRouter(prefix="/auth", tags=["Authentification"])

@router.post(
    "/register",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription d'un nouvel utilisateur"
)
async def register(
    user_data: schemas.UserCreate,
    db: Session = Depends(get_db)
) -> Any:
    """
    Inscription d'un nouvel utilisateur:
    
    - **email**: Email valide (unique)
    - **password**: Mot de passe (min 6 caractères)
    - **username**: Nom d'utilisateur (unique)
    
    Le premier utilisateur inscrit devient automatiquement administrateur.
    """
    # Vérifier si l'email existe déjà
    #query est pour 
    existing_email = db.query(models.User).filter(
        models.User.email == user_data.email
    ).first()
    
    if existing_email:
        #HTTPException est pour gérer les erreurs HTTP, ici on retourne une erreur 400 si l'email est déjà utilisé
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cet email est déjà utilisé"
        )
    
    # Vérifier si le nom d'utilisateur existe déjà
    existing_username = db.query(models.User).filter(
        models.User.username == user_data.username
    ).first()
    
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce nom d'utilisateur est déjà pris"
        )
    
    # Vérifier si c'est le premier utilisateur (devient admin)
    is_first_user = db.query(models.User).count() == 0
    
    # Hasher le mot de passe
    hashed_password = auth.get_password_hash(user_data.password)
    
    # Créer l'utilisateur
    new_user = models.User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hashed_password,
        is_active=True,
        is_admin=is_first_user,  # Premier utilisateur = admin
        auth_provider="local"
    )
    
    # Sauvegarder dans la base de données
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@router.post(
    "/login",
    response_model=schemas.Token,
    summary="Connexion utilisateur"
)
async def login(
    user_data: schemas.UserLogin,
    db: Session = Depends(get_db)
) -> Any:
    """
    Connexion d'un utilisateur:
    
    - **email**: Email de l'utilisateur
    - **password**: Mot de passe
    
    Retourne un token JWT à utiliser pour les requêtes authentifiées.
    """
    # Rechercher l'utilisateur par email
    user = db.query(models.User).filter(
        models.User.email == user_data.email
    ).first()
    
    # Vérifier les identifiants
    if not user or not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect"
        )
    
    # Vérifier si le compte est actif
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte désactivé"
        )
    
    # Créer le token
    access_token = auth.create_access_token(
        data={
            "sub": user.email,
            "role": "admin" if user.is_admin else "user",
            "user_id": user.id,
            "username": user.username
        }
    )
    
    # Retourner le token et les informations
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": "admin" if user.is_admin else "user",
        "user_id": user.id,
        "username": user.username,
        "email": user.email
    }