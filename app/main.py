"""
FICHIER: main.py
ROLE: Point d'entrée de l'application FastAPI
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routers import auth, users, admin
from database import engine, Base

# Charger les variables d'environnement
load_dotenv()

# ========== CRÉATION DES TABLES ==========
print("🗄️  Création des tables dans la base de données...")
Base.metadata.create_all(bind=engine)
print("✅ Tables créées avec succès!")

# ========== CRÉATION DE L'APPLICATION ==========
app = FastAPI(
    title="API d'authentification",
    description="""
    API complète d'authentification avec :
    * Inscription et connexion
    * Protection par JWT
    * Rôles (utilisateur / administrateur)
    * Routes administrateur sécurisées
    """,
    version="1.0.0",
    contact={
        "name": "Support API",
        "email": "support@example.com",
    },
    license_info={
        "name": "MIT",
    },
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
)

# ========== CONFIGURATION CORS ==========
# Récupérer les URLs frontend depuis .env
# ========== CONFIGURATION CORS AMÉLIORÉE ==========
# Récupérer les URLs frontend depuis .env
frontend_urls = os.getenv("FRONTEND_URLS", "http://localhost:5173,http://localhost:3039")
allow_origins = [url.strip() for url in frontend_urls.split(",")]

origins = [
    "http://localhost:3000",  # en local
    "https://price-comparison-platform-seven.vercel.app",  # en production
]

# Ajouter aussi localhost:5173 qui est le port par défaut de Vite
if "http://localhost:5173" not in allow_origins:
    allow_origins.append("http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Spécifier OPTIONS explicitement
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600  # Cache les résultats CORS pour 10 minutes
)

# ========== INCLUSION DES ROUTERS ==========
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)

# ========== ROUTES DE TEST ==========
@app.get("/", tags=["Root"])
async def root():
    """
    Route de bienvenue pour vérifier que l'API fonctionne
    """
    return {
        "message": "🚀 API d'authentification opérationnelle!",
        "version": "1.0.0",
        "documentation": {
            "swagger": "/docs",
            "redoc": "/redoc"
        },
        "endpoints": {
            "auth": "/auth",
            "users": "/users",
            "admin": "/admin"
        }
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Vérification de l'état de l'API
    """
    return {
        "status": "healthy",
        "database": "connected",
        "timestamp": datetime.utcnow().isoformat()
    }

from datetime import datetime


import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)) # 8000 sera le fallback en local
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)