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
    Service 2 lit la DB partagée créée par Service 1.
    On vérifie juste que la connexion fonctionne.
    On ne crée AUCUNE table ici.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
            logger.info(f"[DB] Connexion OK — {result} produits trouvés dans la DB partagée")
    except Exception as e:
        logger.error(f"[DB] Erreur de connexion à la base partagée : {e}")
        logger.error(f"[DB] DATABASE_URL utilisée : {DATABASE_URL}")
        raise
