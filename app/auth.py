"""
FICHIER: auth.py
ROLE: Fonctions de sécurité, hash, JWT et dépendances
"""

import os
import hashlib
import secrets
import hmac
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from dotenv import load_dotenv

import models, schemas
from database import get_db

# Charger les variables d'environnement
load_dotenv()

# Configuration JWT depuis .env
SECRET_KEY = os.getenv("SECRET_KEY", "clé_par_défaut_à_changer")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

# Schéma OAuth2 pour extraire le token de l'en-tête Authorization
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# ========== FONCTIONS DE HASH ==========

def get_password_hash(password: str) -> str:
    """
    Hash un mot de passe avec PBKDF2
    Format: pbkdf2_sha256$itérations$sel$hash
    """
    algorithm = 'pbkdf2_sha256'
    iterations = 260000  # Recommandé pour 2024
    #token_hex génère un sel aléatoire de 32 bytes (64 caractères hexadécimaux)
    salt = secrets.token_hex(32)  # Sel de 32 bytes
    
    # Calcul du hash
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations
    )
    
    hash_hex = hash_bytes.hex()
    return f"{algorithm}${iterations}${salt}${hash_hex}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie si le mot de passe correspond au hash
    """
    try:
        parts = hashed_password.split('$')
        if len(parts) != 4:
            return False
            
        algorithm, iterations_str, salt, stored_hash = parts
        
        if algorithm != 'pbkdf2_sha256':
            return False
            
        iterations = int(iterations_str)
        
        # Recalculer le hash
        hash_bytes = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        
        calculated_hash = hash_bytes.hex()
        
        # Comparaison en temps constant
        return hmac.compare_digest(calculated_hash, stored_hash)
        
    except Exception:
        return False

# ========== FONCTIONS JWT ==========

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crée un token JWT apres lauthentification réussie
    """
    #.copy() pour éviter de modifier le dictionnaire original
    #data contient les informations à encoder dans le token (ex: email, role, user_id)
    #to_encode est une copie de data qui sera modifiée pour ajouter l'expiration
    to_encode = data.copy()
    
    # Définir l'expiration
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    #Ajouter l'expiration au payload du token
    to_encode.update({"exp": expire})
    
    # Créer le token
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[schemas.TokenData]:
    """
    Vérifie et décode un token JWT
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        #payload.get("sub") correspond à l'email de l'utilisateur, c'est la convention pour identifier le sujet du token
        #payload est un dictionnaire contenant les données encodées dans le token, comme l'email, le rôle, l'user_id, etc. 
        email = payload.get("sub")
        role = payload.get("role")
        user_id = payload.get("user_id")
        username = payload.get("username")
        
        if email is None:
            return None
            
        return schemas.TokenData(
            email=email,
            role=role,
            user_id=user_id,
            username=username
        )
    except JWTError:
        return None

# ========== DÉPENDANCES D'AUTHENTIFICATION ==========

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> models.User:
    """
    Récupère l'utilisateur courant à partir du token
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Identifiants invalides",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Vérifier le token
    token_data = verify_token(token)
    if token_data is None or token_data.email is None:
        raise credentials_exception
    
    # Récupérer l'utilisateur
    user = db.query(models.User).filter(
        models.User.email == token_data.email
    ).first()
    
    if user is None:
        raise credentials_exception
    
    return user

async def get_current_active_user(
    current_user: models.User = Depends(get_current_user)
) -> models.User:
    """
    Vérifie que l'utilisateur est actif
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compte inactif"
        )
    return current_user

async def get_current_admin_user(
    current_user: models.User = Depends(get_current_active_user)
) -> models.User:
    """
    Vérifie que l'utilisateur est administrateur
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs"
        )
    return current_user