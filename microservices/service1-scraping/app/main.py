"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SERVICE 1 – Scraping  (port 8001)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ROUTES
  ── Sync URLs ──────────────────────────────────
  POST   /scrape/sync-urls
  GET    /category-urls
  GET    /category-urls/stats

  ── Scraping produits ──────────────────────────
  POST   /scrape/start
  GET    /scrape/status/{task_id}
  POST   /scrape/cancel/{task_id}
  GET    /scrape/history
  GET    /scrape/categories/{site}

  ── Produits ───────────────────────────────────
  GET    /products
  GET    /products/search
  GET    /products/stats
  GET    /products/{id}
  DELETE /products/boutique/{b}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys
import asyncio
import logging
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app import crud, schemas
from app.scraper_service import (
    start_scrape_task,
    start_sync_urls_task,
    cancel_scrape_task,
    get_available_categories,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Service 1 – Scraping",
    description=(
        "Microservice responsable du **scraping** des produits tunisiens.\n\n"
        "**Flux :**\n"
        "1. `POST /scrape/sync-urls` — synchronise les URLs de catégories\n"
        "2. `POST /scrape/start` — lance le scraping des produits\n"
        "3. `GET /products` — consulte les produits scrappés\n\n"
        "Port : **8001**"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    logger.info("Service 1 – Scraping démarré")
    init_db()


# ── Santé ──────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Général"])
def health_check():
    return {"status": "ok", "service": "scraping", "port": 8001}


# ── Sync URLs ──────────────────────────────────────────────────────────────────

@app.post("/scrape/sync-urls", status_code=202, tags=["Sync URLs"])
def sync_category_urls(db: Session = Depends(get_db)):
    """Étape 1 — Scrape les menus des 3 sites et stocke les URLs en DB."""
    task_id = start_sync_urls_task(db)
    return {
        "task_id":    task_id,
        "message":    "Synchronisation des catégories lancée.",
        "status_url": f"/scrape/status/{task_id}",
    }


@app.get("/category-urls", tags=["Sync URLs"])
def list_category_urls(
    boutique:    Optional[str] = Query(None),
    rayon:       Optional[str] = Query(None),
    active_only: bool          = Query(True),
    db:          Session       = Depends(get_db),
):
    cats = crud.get_category_urls(db, boutique=boutique, rayon=rayon, active_only=active_only)
    return {
        "total": len(cats),
        "data": [
            {
                "id": c.id, "boutique": c.boutique, "rayon": c.rayon,
                "sous_categorie": c.sous_categorie, "url": c.url,
                "active": c.active, "last_scraped": c.last_scraped,
                "created_at": c.created_at,
            }
            for c in cats
        ],
    }


@app.get("/category-urls/stats", tags=["Sync URLs"])
def category_urls_stats(db: Session = Depends(get_db)):
    from app.models import CategoryUrl
    from sqlalchemy import func as sqlfunc
    rows = (
        db.query(
            CategoryUrl.boutique,
            sqlfunc.count(CategoryUrl.id).label("total"),
            sqlfunc.count(CategoryUrl.last_scraped).label("scraped"),
        ).group_by(CategoryUrl.boutique).all()
    )
    return {
        "total_urls": crud.count_category_urls(db),
        "par_boutique": [
            {"boutique": r.boutique, "total": r.total,
             "scraped": r.scraped, "remaining": r.total - r.scraped}
            for r in rows
        ],
    }


# ── Scraping produits ──────────────────────────────────────────────────────────

@app.post("/scrape/start", status_code=202, tags=["Scraping"])
def start_scraping(request: schemas.ScrapeRequest, db: Session = Depends(get_db)):
    """Étape 2 — Scrape les produits depuis les URLs en DB."""
    if request.site.value != "all":
        label_map = {"spacenet": "Spacenet", "tunisianet": "Tunisianet", "mytek": "Mytek"}
        boutique  = label_map.get(request.site.value, "")
        if crud.count_category_urls(db, boutique=boutique) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Aucune URL trouvée pour '{request.site}'. Lancez d'abord /scrape/sync-urls.",
            )
    task_id = start_scrape_task(db=db, site=request.site.value,
                                categories=request.categories, max_pages=request.max_pages)
    return {
        "task_id":    task_id,
        "message":    f"Scraping '{request.site}' lancé en arrière-plan.",
        "status_url": f"/scrape/status/{task_id}",
    }


@app.get("/scrape/status/{task_id}", response_model=schemas.ScrapeTaskResponse, tags=["Scraping"])
def get_task_status(task_id: str, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Tâche '{task_id}' introuvable.")
    return task


@app.post("/scrape/cancel/{task_id}", tags=["Scraping"])
def cancel_scraping(task_id: str, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Tâche '{task_id}' introuvable.")
    if task.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Tâche déjà '{task.status}'.")
    if not cancel_scrape_task(task_id):
        raise HTTPException(status_code=400, detail="Tâche plus active.")
    return {"message": "Signal d'arrêt envoyé.", "task_id": task_id}


@app.get("/scrape/history", response_model=List[schemas.ScrapeTaskResponse], tags=["Scraping"])
def get_scrape_history(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return crud.get_tasks(db, limit=limit)


@app.get("/scrape/categories/{site}", response_model=schemas.CategoriesResponse, tags=["Scraping"])
def list_categories(site: schemas.SiteEnum):
    if site == schemas.SiteEnum.ALL:
        raise HTTPException(status_code=400, detail="Utilisez un site spécifique.")
    categories = get_available_categories(site.value)
    if categories is None:
        raise HTTPException(status_code=404, detail=f"Site '{site}' inconnu.")
    return {"site": site, "categories": categories}


# ── Produits ───────────────────────────────────────────────────────────────────

@app.get("/products", response_model=schemas.ProductListResponse, tags=["Produits"])
def list_products(
    boutique:  Optional[str]        = Query(None),
    categorie: Optional[str]        = Query(None),
    prix_min:  Optional[float]      = Query(None, ge=0),
    prix_max:  Optional[float]      = Query(None, ge=0),
    sort_by:   schemas.SortByEnum   = Query(schemas.SortByEnum.RECENT),
    page:      int                  = Query(1, ge=1),
    per_page:  int                  = Query(20, ge=1, le=100),
    db:        Session              = Depends(get_db),
):
    return crud.get_products(
        db, boutique=boutique, categorie=categorie,
        prix_min=prix_min, prix_max=prix_max,
        sort_by=sort_by.value, page=page, per_page=per_page,
    )


@app.get("/products/search", response_model=schemas.SearchResponse, tags=["Produits"])
def search_products(
    q:     str = Query(..., min_length=2),
    limit: int = Query(50, ge=1, le=200),
    db:    Session = Depends(get_db),
):
    products = crud.search_products(db, query_str=q, limit=limit)
    return {"query": q, "total": len(products), "data": products}


@app.get("/products/stats", response_model=schemas.GlobalStats, tags=["Produits"])
def get_stats(db: Session = Depends(get_db)):
    return crud.get_stats(db)


@app.get("/products/{product_id}", response_model=schemas.ProductResponse, tags=["Produits"])
def get_product(product_id: int, db: Session = Depends(get_db)):
    from app.models import Product
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Produit {product_id} introuvable.")
    return product


@app.delete("/products/boutique/{boutique}", tags=["Produits"])
def delete_products(boutique: str, db: Session = Depends(get_db)):
    count = crud.delete_products_by_boutique(db, boutique)
    if count == 0:
        raise HTTPException(status_code=404, detail=f"Aucun produit pour '{boutique}'.")
    return {"message": f"{count} produits supprimés pour '{boutique}'.", "deleted": count}
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)) # 8000 sera le fallback en local
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)