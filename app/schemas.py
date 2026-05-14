"""
FICHIER: schemas.py
RÔLE: Schémas Pydantic pour la validation et la sérialisation des données
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime

# ========== SCHÉMAS DE BASE ==========

class UserBase(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None      # ← Changer str en Optional[str]
    is_active: bool
    is_admin: bool = False
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# ========== SCHÉMAS POUR LES REQUÊTES (ENTRÉE) ==========

class UserCreate(BaseModel):
    """
    Schéma pour la création d'un utilisateur (inscription)
    """
    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., min_length=6, description="Mot de passe (min 6 caractères)")
    username: str = Field(..., min_length=3, max_length=50, description="Nom d'utilisateur")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "password123",
                "username": "john_doe"
            }
        }


class UserLogin(BaseModel):
    """
    Schéma pour la connexion
    """
    email: EmailStr
    password: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "password123"
            }
        }


# ========== SCHÉMAS POUR LES RÉPONSES (SORTIE) ==========

# ATTENTION : UserResponse N'A PAS de mot de passe !
# C'est ce qui corrige ton erreur 500 'password field required'.
class UserResponse(UserBase):
    """
    Schéma de réponse pour les données utilisateur.
    Hérite de UserBase (id, email, username, is_active, etc.)
    """
    
    class Config:
        # Important : Permet de lire depuis la DB directement
        from_attributes = True


class Token(BaseModel):
    """
    Réponse après connexion réussie
    """
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    username: str
    email: EmailStr
    
    class Config:
        from_attributes = True


class TokenData(BaseModel):
    """
    Données extraites du token JWT
    """
    email: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[int] = None
    username: Optional[str] = None