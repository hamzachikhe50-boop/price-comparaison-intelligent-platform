"""
FICHIER: models.py
ROLE: Définition des modèles SQLAlchemy (tables de la base de données)
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base

class User(Base):
    """
    Modèle utilisateur pour la table 'users'
    """
    
    __tablename__ = "liste_utilisateurs"

    # Identifiants
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)
    
    # Sécurité
    hashed_password = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    
    # Authentification externe
    auth_provider = Column(String, default="local")  # 'local' ou 'google'
    google_id = Column(String, unique=True, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        """Représentation de l'objet pour le débogage"""
        return f"<User {self.email}>"