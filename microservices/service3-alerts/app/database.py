from pathlib import Path
import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Charge le .env du dossier service, peu importe d'ou uvicorn est lance
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:123456@localhost/scraper_db"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Service 3 crée UNIQUEMENT la table 'alerts' (sa propre table).
    La table 'products' est créée et gérée par Service 1.
    On vérifie aussi que la connexion à la DB partagée fonctionne.
    """
    from app.models import Alert, Favorite  # noqa — importe seulement Alert et Favorite

    # Créer uniquement la table alerts
    Alert.__table__.create(bind=engine, checkfirst=True)
    Favorite.__table__.create(bind=engine, checkfirst=True)

    logger.info("[DB] Table 'alerts' vérifiée/créée")

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
            logger.info(f"[DB] Connexion OK — {result} produits trouvés dans la DB partagée")
    except Exception as e:
        logger.error(f"[DB] Erreur d'accès à la table 'products' : {e}")
        logger.error(f"[DB] Assurez-vous que Service 1 a déjà lancé un scraping.")
        logger.error(f"[DB] DATABASE_URL utilisée : {DATABASE_URL}")
