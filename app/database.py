"""
FICHIER: database.py
ROLE: Configuration de la connexion à PostgreSQL
"""
#os pour gérer les variables d'environnement
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Récupérer l'URL de la base de données depuis .env
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres.erzutohrpvmrbccdnlig:authHamza123@aws-0-eu-west-1.pooler.supabase.com:6543/postgres")

# Créer le moteur de connexion
engine = create_engine(DATABASE_URL)

# Créer la fabrique de sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Classe de base pour les modèles
Base = declarative_base()

def get_db():
    """
    Dépendance pour obtenir une session de base de données
    À utiliser dans les routes FastAPI
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()