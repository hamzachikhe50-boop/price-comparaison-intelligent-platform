"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  models.py – Service 1 : Scraping
  Tables : category_urls, products, scrape_tasks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import enum
from sqlalchemy import (
    Column, Integer, String, Text,
    Float, DateTime, Enum, Index, Boolean, Date, UniqueConstraint
)
from sqlalchemy.sql import func
from app.database import Base


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


class CategoryUrl(Base):
    __tablename__ = "category_urls"

    id             = Column(Integer, primary_key=True, index=True)
    boutique       = Column(String(100), nullable=False, index=True)
    rayon          = Column(String(200), nullable=False)
    sous_categorie = Column(String(200), nullable=False)
    url            = Column(Text, nullable=False, unique=True)
    active         = Column(Boolean, default=True, nullable=False)
    last_scraped   = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_caturl_boutique_rayon", "boutique", "rayon"),
    )


class Product(Base):
    __tablename__ = "products"

    id              = Column(Integer, primary_key=True, index=True)
    nom             = Column(String(500), nullable=False)
    prix            = Column(String(100))
    prix_num        = Column(Float, nullable=True)
    image           = Column(Text)
    lien            = Column(Text)
    boutique        = Column(String(100), nullable=False, index=True)
    categorie       = Column(String(200), nullable=False, index=True)
    rayon           = Column(String(200), nullable=True)
    sous_categorie  = Column(String(200), nullable=True)
    category_url_id = Column(Integer, nullable=True, index=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_product_boutique_lien", "boutique", "lien"),
    )


class ScrapeTask(Base):
    __tablename__ = "scrape_tasks"

    id      = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(100), unique=True, index=True)
    site    = Column(String(50), nullable=False)
    categories     = Column(Text, nullable=True)
    status         = Column(Enum(TaskStatus, native_enum=False), default=TaskStatus.PENDING, index=True)
    total_scraped  = Column(Integer, default=0)
    total_inserted = Column(Integer, default=0)
    total_updated  = Column(Integer, default=0)
    error_message  = Column(Text, nullable=True)
    started_at     = Column(DateTime(timezone=True), server_default=func.now())
    finished_at    = Column(DateTime(timezone=True), nullable=True)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id               = Column(Integer, primary_key=True, index=True)
    product_id       = Column(Integer, nullable=False, index=True)
    ancien_prix      = Column(Float, nullable=True)
    nouveau_prix     = Column(Float, nullable=True)
    ancien_prix_txt  = Column(String(100), nullable=True)
    nouveau_prix_txt = Column(String(100), nullable=True)
    scrape_date      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pricehistory_product_date", "product_id", "scrape_date"),
    )


class PriceDaily(Base):
    __tablename__ = "price_daily"

    id         = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    prix_num   = Column(Float, nullable=True)
    prix_txt   = Column(String(100), nullable=True)
    jour       = Column(Date, nullable=False)

    __table_args__ = (
        UniqueConstraint("product_id", "jour", name="uq_product_jour"),
        Index("ix_pricedaily_product_jour", "product_id", "jour"),
    )
