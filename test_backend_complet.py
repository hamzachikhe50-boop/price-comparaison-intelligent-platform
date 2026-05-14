# test_backend_complet.py
import requests
import json
import time
import sys
from sqlalchemy import create_engine, text, inspect
import psycopg2

print("="*60)
print("🧪 TEST COMPLET DU BACKEND")
print("="*60)

# Configuration
BASE_URL = "http://localhost:8000"
DB_CONFIG = {
    "database": "auth_db",
    "user": "postgres",
    "password": "postgres",  # À MODIFIER selon votre configuration
    "host": "localhost",
    "port": "5432"
}

# Compteur de tests
tests_total = 0
tests_reussis = 0

def test_step(description, fonction_test):
    """Fonction helper pour exécuter un test"""
    global tests_total, tests_reussis
    tests_total += 1
    print(f"\n📌 Test {tests_total}: {description}")
    print("-" * 40)
    
    try:
        fonction_test()
        print(f"✅ RÉUSSI")
        tests_reussis += 1
    except AssertionError as e:
        print(f"❌ ÉCHEC: {e}")
    except Exception as e:
        print(f"❌ ERREUR: {type(e).__name__}: {e}")

print("\n" + "="*60)
print("PARTIE 1: VÉRIFICATION DE LA BASE DE DONNÉES")
print("="*60)

# TEST 1: PostgreSQL est-il installé ?
def test_postgres_installe():
    import subprocess
    try:
        result = subprocess.run(['psql', '--version'], capture_output=True, text=True)
        assert result.returncode == 0, "PostgreSQL n'est pas installé ou pas dans le PATH"
        print(f"   Version: {result.stdout.strip()}")
    except FileNotFoundError:
        raise AssertionError("PostgreSQL n'est pas installé")

test_step("PostgreSQL est installé", test_postgres_installe)

# TEST 2: Connexion à PostgreSQL
def test_connexion_postgres():
    conn = psycopg2.connect(
        database="postgres",
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"]
    )
    conn.close()
    print("   ✅ Connexion réussie à PostgreSQL")

test_step("Connexion à PostgreSQL", test_connexion_postgres)

# TEST 3: La base de données existe
def test_base_existe():
    conn = psycopg2.connect(
        database="postgres",
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"]
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{DB_CONFIG['database']}'")
    exists = cur.fetchone()
    cur.close()
    conn.close()
    assert exists, f"La base de données '{DB_CONFIG['database']}' n'existe pas"
    print(f"   ✅ Base de données '{DB_CONFIG['database']}' trouvée")

test_step("Base de données existe", test_base_existe)

print("\n" + "="*60)
print("PARTIE 2: VÉRIFICATION DES MODÈLES")
print("="*60)

# TEST 4: Création des tables
def test_creation_tables():
    from app.database import engine, Base
    from app import models
    
    # Supprimer les tables existantes (optionnel, pour test)
    # Base.metadata.drop_all(bind=engine)
    
    # Créer les tables
    Base.metadata.create_all(bind=engine)
    
    # Vérifier que les tables existent
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert 'users' in tables, "La table 'users' n'a pas été créée"
    print(f"   ✅ Tables créées: {tables}")

test_step("Création des tables", test_creation_tables)

print("\n" + "="*60)
print("PARTIE 3: VÉRIFICATION DE L'API")
print("="*60)

# TEST 5: Le serveur FastAPI est-il lancé ?
def test_serveur_repond():
    try:
        response = requests.get(f"{BASE_URL}/")
        assert response.status_code == 200
        data = response.json()
        print(f"   ✅ Message: {data.get('message', 'N/A')}")
    except requests.exceptions.ConnectionError:
        raise AssertionError(f"Le serveur n'est pas accessible sur {BASE_URL}\n   Lancez: uvicorn app.main:app --reload")

test_step("Serveur FastAPI répond", test_serveur_repond)

# TEST 6: Documentation Swagger
def test_swagger_disponible():
    response = requests.get(f"{BASE_URL}/docs")
    assert response.status_code == 200
    print("   ✅ Documentation Swagger disponible")

test_step("Documentation Swagger", test_swagger_disponible)

print("\n" + "="*60)
print("PARTIE 4: TEST DES ROUTES D'AUTHENTIFICATION")
print("="*60)

# Variables pour stocker les tokens
test_user = {
    "email": f"test{int(time.time())}@example.com",
    "password": "Test123456!",
    "username": "testuser",
    "full_name": "Test User"
}
access_token = None

# TEST 7: Inscription
def test_inscription():
    global test_user
    response = requests.post(
        f"{BASE_URL}/auth/register",
        json=test_user
    )
    assert response.status_code == 200, f"Statut: {response.status_code}"
    data = response.json()
    assert "access_token" in data, "Pas de token dans la réponse"
    print(f"   ✅ Utilisateur créé: {test_user['email']}")

test_step("Inscription utilisateur", test_inscription)

# TEST 8: Connexion
def test_connexion():
    global access_token
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": test_user["email"],
            "password": test_user["password"]
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    access_token = data["access_token"]
    print("   ✅ Connexion réussie")

test_step("Connexion utilisateur", test_connexion)

# TEST 9: Récupérer profil (/me)
def test_get_me():
    global access_token
    assert access_token is not None, "Pas de token disponible"
    
    response = requests.get(
        f"{BASE_URL}/auth/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user["email"]
    print(f"   ✅ Profil récupéré: {data['email']}")

test_step("Récupération profil", test_get_me)

# TEST 10: Route protégée sans token (doit échouer)
def test_route_protegee_sans_token():
    response = requests.get(f"{BASE_URL}/auth/me")
    assert response.status_code == 401, f"Devrait être 401, reçu {response.status_code}"
    print("   ✅ Accès refusé sans token (normal)")

test_step("Route protégée sans token", test_route_protegee_sans_token)

print("\n" + "="*60)
print("PARTIE 5: VÉRIFICATION DANS LA BASE DE DONNÉES")
print("="*60)

# TEST 11: Vérifier que l'utilisateur est en BDD
def test_utilisateur_en_bdd():
    from app.database import SessionLocal
    from app.models import User
    
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == test_user["email"]).first()
        assert user is not None, "Utilisateur non trouvé en BDD"
        print(f"   ✅ Utilisateur trouvé en BDD: {user.email}")
        print(f"     ID: {user.id}")
        print(f"     Admin: {user.is_admin}")
        print(f"     Actif: {user.is_active}")
    finally:
        db.close()

test_step("Utilisateur en base de données", test_utilisateur_en_bdd)

print("\n" + "="*60)
print("📊 RÉSULTATS FINAUX")
print("="*60)
print(f"Tests réussis: {tests_reussis}/{tests_total}")

if tests_reussis == tests_total:
    print("\n🎉 FÉLICITATIONS! Votre backend fonctionne parfaitement!")
    print("\n🚀 Vous pouvez maintenant:")
    print("   1. Lancer le frontend React")
    print("   2. Tester l'interface utilisateur")
    print("   3. Commencer à développer les fonctionnalités de votre projet")
else:
    print(f"\n⚠️  {tests_total - tests_reussis} test(s) ont échoué")
    print("\n🔧 Vérifiez les erreurs ci-dessus")

print("\n" + "="*60)