"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  crud.py – Service 1 : Scraping
  Opérations DB : produits, tasks, category_urls
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import re
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func, or_, asc, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import (
    Product, ScrapeTask, TaskStatus, CategoryUrl, PriceHistory, PriceDaily
)

logger = logging.getLogger(__name__)


# ─── Parser de prix ────────────────────────────────────────────────────────────

def parse_price(prix_str: Optional[str]) -> Optional[float]:
    if not prix_str:
        return None
    cleaned = (
        prix_str
        .replace("\xa0", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    match = re.search(r"\d+\.?\d*", cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


# ─── Produits ──────────────────────────────────────────────────────────────────

def upsert_products(db: Session, products: List[Dict]) -> Dict[str, int]:
    """Insère ou met à jour les produits + PriceHistory + PriceDaily."""
    inserted = 0
    updated = 0
    aujourd_hui = date.today()
    liens_traites = set()

    for p in products:
        lien     = p.get("lien")
        boutique = p.get("boutique")

        if lien and lien in liens_traites:
            continue
        if lien:
            liens_traites.add(lien)

        prix_num = parse_price(p.get("prix"))

        existing = None
        if lien:
            existing = (
                db.query(Product)
                .filter(Product.boutique == boutique, Product.lien == lien)
                .first()
            )

        if existing:
            # Enregistrer dans price_history SEULEMENT si le prix a change
            if existing.prix_num != prix_num:
                db.add(PriceHistory(
                    product_id       = existing.id,
                    ancien_prix      = existing.prix_num,
                    nouveau_prix     = prix_num,
                    ancien_prix_txt  = existing.prix,
                    nouveau_prix_txt = p.get("prix"),
                ))

            if existing.prix != p.get("prix") or existing.nom != p.get("nom"):
                existing.nom        = p.get("nom")
                existing.prix       = p.get("prix")
                existing.prix_num   = prix_num
                existing.image      = p.get("image")
                existing.categorie  = p.get("categorie")
                existing.updated_at = datetime.utcnow()
                updated += 1

            stmt = pg_insert(PriceDaily).values(
                product_id=existing.id, prix_num=prix_num,
                prix_txt=p.get("prix"), jour=aujourd_hui
            ).on_conflict_do_update(
                constraint='uq_product_jour',
                set_=dict(prix_num=prix_num, prix_txt=p.get("prix"))
            )
            db.execute(stmt)
        else:
            db_product = Product(
                nom=p.get("nom"), prix=p.get("prix"), prix_num=prix_num,
                image=p.get("image"), lien=lien,
                boutique=boutique, categorie=p.get("categorie"),
            )
            db.add(db_product)
            db.flush()

            stmt = pg_insert(PriceDaily).values(
                product_id=db_product.id, prix_num=prix_num,
                prix_txt=p.get("prix"), jour=aujourd_hui
            ).on_conflict_do_update(
                constraint='uq_product_jour',
                set_=dict(prix_num=prix_num, prix_txt=p.get("prix"))
            )
            db.execute(stmt)
            inserted += 1

    db.commit()
    logger.info(f"[crud] upsert : {inserted} insérés, {updated} mis à jour")
    return {"inserted": inserted, "updated": updated}


def get_products(
    db: Session,
    boutique: Optional[str] = None,
    categorie: Optional[str] = None,
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    sort_by: str = "recent",
    page: int = 1,
    per_page: int = 20,
) -> Dict[str, Any]:
    query = db.query(Product)
    if boutique:
        query = query.filter(Product.boutique.ilike(f"%{boutique}%"))
    if categorie:
        query = query.filter(Product.categorie.ilike(f"%{categorie}%"))
    if prix_min is not None:
        query = query.filter(Product.prix_num >= prix_min)
    if prix_max is not None:
        query = query.filter(Product.prix_num <= prix_max)

    order_map = {
        "prix_asc":  asc(Product.prix_num),
        "prix_desc": desc(Product.prix_num),
        "recent":    desc(Product.created_at),
        "nom":       asc(Product.nom),
    }
    query = query.order_by(order_map.get(sort_by, desc(Product.created_at)))
    total    = query.count()
    pages    = max(1, (total + per_page - 1) // per_page)
    items    = query.offset((page - 1) * per_page).limit(per_page).all()
    return {"total": total, "page": page, "per_page": per_page, "pages": pages, "data": items}


def search_products(db: Session, query_str: str, limit: int = 50) -> List[Product]:
    return (
        db.query(Product)
        .filter(or_(
            Product.nom.ilike(f"%{query_str}%"),
            Product.categorie.ilike(f"%{query_str}%"),
        ))
        .order_by(asc(Product.nom))
        .limit(limit)
        .all()
    )


def get_stats(db: Session) -> Dict[str, Any]:
    total_products = db.query(func.count(Product.id)).scalar()
    by_boutique = (
        db.query(
            Product.boutique,
            func.count(Product.id).label("total"),
            func.count(func.distinct(Product.categorie)).label("categories"),
        ).group_by(Product.boutique).all()
    )
    by_categorie = (
        db.query(
            Product.categorie, Product.boutique,
            func.count(Product.id).label("total"),
            func.min(Product.prix_num).label("prix_min"),
            func.max(Product.prix_num).label("prix_max"),
            func.avg(Product.prix_num).label("prix_moyen"),
        ).group_by(Product.categorie, Product.boutique)
        .order_by(desc(func.count(Product.id))).all()
    )
    last_task = (
        db.query(ScrapeTask)
        .filter(ScrapeTask.status == TaskStatus.DONE)
        .order_by(desc(ScrapeTask.finished_at))
        .first()
    )
    return {
        "total_products": total_products,
        "by_boutique": [{"boutique": r.boutique, "total": r.total, "categories": r.categories} for r in by_boutique],
        "by_categorie": [
            {"categorie": r.categorie, "boutique": r.boutique, "total": r.total,
             "prix_min":   round(r.prix_min, 3)   if r.prix_min   else None,
             "prix_max":   round(r.prix_max, 3)   if r.prix_max   else None,
             "prix_moyen": round(r.prix_moyen, 3) if r.prix_moyen else None}
            for r in by_categorie
        ],
        "last_scrape": last_task.finished_at if last_task else None,
    }


def delete_products_by_boutique(db: Session, boutique: str) -> int:
    count = db.query(Product).filter(Product.boutique == boutique).delete()
    db.commit()
    return count


# ─── Tâches ────────────────────────────────────────────────────────────────────

def create_task(db: Session, task_id: str, site: str, categories: Optional[List[str]] = None) -> ScrapeTask:
    task = ScrapeTask(
        task_id=task_id, site=site,
        categories=json.dumps(categories, ensure_ascii=False) if categories else None,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task_status(
    db: Session, task_id: str, status: TaskStatus,
    total_scraped: int = 0, total_inserted: int = 0,
    total_updated: int = 0, error_message: Optional[str] = None,
) -> Optional[ScrapeTask]:
    task = db.query(ScrapeTask).filter(ScrapeTask.task_id == task_id).first()
    if not task:
        return None
    task.status         = status
    task.total_scraped  = total_scraped
    task.total_inserted = total_inserted
    task.total_updated  = total_updated
    task.error_message  = error_message
    if status in (TaskStatus.DONE, TaskStatus.FAILED):
        task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: str) -> Optional[ScrapeTask]:
    return db.query(ScrapeTask).filter(ScrapeTask.task_id == task_id).first()


def get_tasks(db: Session, limit: int = 20) -> List[ScrapeTask]:
    return db.query(ScrapeTask).order_by(desc(ScrapeTask.started_at)).limit(limit).all()


# ─── CategoryUrls ──────────────────────────────────────────────────────────────

def upsert_category_urls(db: Session, items: List[Dict]) -> Dict[str, int]:
    inserted = updated = 0
    for item in items:
        url = item.get("url", "").strip()
        if not url:
            continue
        existing = db.query(CategoryUrl).filter(CategoryUrl.url == url).first()
        if existing:
            changed = False
            for field in ("rayon", "sous_categorie", "boutique"):
                if getattr(existing, field) != item.get(field, ""):
                    setattr(existing, field, item.get(field, ""))
                    changed = True
            if changed:
                updated += 1
        else:
            db.add(CategoryUrl(
                boutique=item.get("boutique", ""), rayon=item.get("rayon", ""),
                sous_categorie=item.get("sous_categorie", ""), url=url, active=True,
            ))
            inserted += 1
    db.commit()
    return {"inserted": inserted, "updated": updated}


def get_category_urls(
    db: Session, boutique: Optional[str] = None,
    rayon: Optional[str] = None, active_only: bool = True,
) -> List[CategoryUrl]:
    q = db.query(CategoryUrl)
    if boutique:
        q = q.filter(CategoryUrl.boutique == boutique)
    if rayon:
        q = q.filter(CategoryUrl.rayon == rayon)
    if active_only:
        q = q.filter(CategoryUrl.active == True)
    return q.order_by(CategoryUrl.boutique, CategoryUrl.rayon, CategoryUrl.sous_categorie).all()


def mark_category_scraped(db: Session, category_url_id: int) -> None:
    cat = db.query(CategoryUrl).filter(CategoryUrl.id == category_url_id).first()
    if cat:
        cat.last_scraped = datetime.now(timezone.utc)
        db.commit()


def count_category_urls(db: Session, boutique: Optional[str] = None) -> int:
    q = db.query(func.count(CategoryUrl.id))
    if boutique:
        q = q.filter(CategoryUrl.boutique == boutique)
    return q.scalar() or 0
