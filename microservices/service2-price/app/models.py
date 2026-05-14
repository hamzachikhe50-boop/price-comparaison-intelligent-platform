"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  models.py – Service 2 : Price History & Prédiction
  Toutes les tables sont créées par Service 1.
  Service 2 les LIT seulement → extend_existing = True
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Date, UniqueConstraint, Index
)
from sqlalchemy.sql import func
from app.database import Base


class Product(Base):
    __tablename__  = "products"
    __table_args__ = {"extend_existing": True}

    id        = Column(Integer, primary_key=True, index=True)
    nom       = Column(String(500), nullable=False)
    prix      = Column(String(100))
    prix_num  = Column(Float, nullable=True)
    image     = Column(Text)
    lien      = Column(Text)
    boutique  = Column(String(100), nullable=False, index=True)
    categorie = Column(String(200), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PriceHistory(Base):
    __tablename__  = "price_history"
    __table_args__ = (
        Index("ix_pricehistory_product_date2", "product_id", "scrape_date"),
        {"extend_existing": True},
    )

    id               = Column(Integer, primary_key=True, index=True)
    product_id       = Column(Integer, nullable=False, index=True)
    ancien_prix      = Column(Float, nullable=True)
    nouveau_prix     = Column(Float, nullable=True)
    ancien_prix_txt  = Column(String(100), nullable=True)
    nouveau_prix_txt = Column(String(100), nullable=True)
    scrape_date      = Column(DateTime(timezone=True), server_default=func.now())


class PriceDaily(Base):
    __tablename__  = "price_daily"
    __table_args__ = (
        UniqueConstraint("product_id", "jour", name="uq_product_jour"),
        Index("ix_pricedaily_product_jour2", "product_id", "jour"),
        {"extend_existing": True},
    )

    id         = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    prix_num   = Column(Float, nullable=True)
    prix_txt   = Column(String(100), nullable=True)
    jour       = Column(Date, nullable=False)
