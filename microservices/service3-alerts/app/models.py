"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  models.py – Service 3 : Alertes de prix

  Alert   → table propre au Service 3 (créée par init_db)
  Product → table créée par Service 1, lue avec extend_existing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean, Index
)
from sqlalchemy.sql import func
from app.database import Base


# ── Table 'products' — lue depuis la DB partagée (Service 1) ──────────────────
# extend_existing = True → ne recrée pas la table si elle existe déjà
class Product(Base):
    __tablename__  = "products"
    __table_args__ = {"extend_existing": True}

    id        = Column(Integer, primary_key=True, index=True)
    nom       = Column(String(500), nullable=False)
    prix      = Column(String(100))
    prix_num  = Column(Float, nullable=True)
    lien      = Column(Text)
    boutique  = Column(String(100), nullable=False, index=True)
    categorie = Column(String(200), nullable=False, index=True)


# ── Table 'alerts' — propre au Service 3 ──────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(String(100), nullable=False, index=True)
    user_email   = Column(String(200), nullable=False)
    product_id   = Column(Integer, nullable=False, index=True)
    product_name = Column(String(500), nullable=True)
    product_url  = Column(String(1000), nullable=True)
    prix_cible   = Column(Float, nullable=False)
    prix_actuel  = Column(Float, nullable=True)
    active       = Column(Boolean, default=True)
    created_at   = Column(DateTime, server_default=func.now())
    triggered_at = Column(DateTime, nullable=True)


# ── Table 'favorites' — propre au Service 3 ──────────────────────────────────
class Favorite(Base):
    __tablename__ = "favorites"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(String(100), nullable=False, index=True)
    product_id   = Column(Integer, nullable=False, index=True)
    product_name = Column(String(500), nullable=True)
    product_url  = Column(String(1000), nullable=True)
    image_url    = Column(String(1000), nullable=True)
    best_price   = Column(Float, nullable=True)
    category     = Column(String(200), nullable=True)
    created_at   = Column(DateTime, server_default=func.now())

    # Contrainte : un utilisateur ne peut pas ajouter le même produit 2 fois
    __table_args__ = (Index('idx_user_product_fav', 'user_id', 'product_id', unique=True),)