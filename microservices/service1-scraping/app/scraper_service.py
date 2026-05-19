"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scraper_service.py  –  Orchestration du scraping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import uuid
import asyncio
import logging
import threading
import time
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any

import httpx
import selectolax.parser
from curl_cffi.requests import AsyncSession

from sqlalchemy.orm import Session

from app import crud
from app.models import TaskStatus
from app.database import SessionLocal
from app.scrapers.spacenet import SpacenetScraper
from app.scrapers.tunisianet import TunisianetScraper
from app.scrapers.mytek import MytekScraper

logger = logging.getLogger(__name__)

# ── Pool de threads (3 max : un par site) ─────────────────────────────────────
executor = ThreadPoolExecutor(max_workers=3)

# ── Registre des scrapers de produits ─────────────────────────────────────────
SCRAPERS = {
    "mytek":      MytekScraper,
    "spacenet":   SpacenetScraper,
    "tunisianet": TunisianetScraper,
}

# ── Drapeaux d'annulation ──────────────────────────────────────────────────────
_cancel_flags: Dict[str, threading.Event] = {}


def _is_cancelled(task_id: str) -> bool:
    flag = _cancel_flags.get(task_id)
    return flag is not None and flag.is_set()


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIE 1 : Sync des URLs de catégories depuis les 3 sites
# ══════════════════════════════════════════════════════════════════════════════

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

HEADERS_MYTEK_API = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
}

HEADERS_MYTEK_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.mytek.tn/",
}

MYTEK_REST_BASE = "https://www.mytek.tn/rest/V1"

# Configuration HTML pour Spacenet et Tunisianet
CONFIGS_HTML = {
    "Spacenet": {
        "url":            "https://spacenet.tn",
        "rayon_selector": "li.vertical-cat",
        "dropdown_selector": ".dropdown-menu",
        "level2_selector": "ul.level-2 > li.cat-child",
    },
    "Tunisianet": {
        "url":            "https://www.tunisianet.com.tn",
        "rayon_selector": "div.wb-menu-vertical ul.menu-content > li.level-1.parent",
        "dropdown_selector": "div.wb-sub-menu",
        "level2_selector": "div.wb-menu-col li.menu-item.item-header",
    },
}


# ── Helpers Mytek ─────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convertit un nom en slug URL (convention Magento)."""
    slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = slug.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def _deduplicate_categories(categories: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for item in categories:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


# ── Sync URLs : Spacenet & Tunisianet (inchangé) ─────────────────────────────

async def _fetch_html_categories(boutique: str) -> List[Dict]:
    config   = CONFIGS_HTML[boutique]
    base_url = config["url"]
    categories_raw: List[Dict] = []

    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS_HTTP) as client:
        try:
            r    = await client.get(base_url)
            tree = selectolax.parser.HTMLParser(r.text)

            for rayon_node in tree.css(config["rayon_selector"]):
                rayon_name = ""

                if boutique == "Tunisianet":
                    icon_div = rayon_node.css_first("div.icon-drop-mobile")
                    if icon_div:
                        name_span = icon_div.css_first("span")
                        if name_span:
                            rayon_name = name_span.text(strip=True)

                if not rayon_name:
                    rayon_link = rayon_node.css_first("a")
                    if rayon_link:
                        title_span = rayon_link.css_first("span.menu-title")
                        if title_span:
                            rayon_name = title_span.text(strip=True)
                        else:
                            rayon_name = rayon_link.text(strip=True)

                if not rayon_name:
                    rayon_name = rayon_node.text(strip=True)

                if not rayon_name or len(rayon_name) < 2:
                    continue

                dropdown = rayon_node.css_first(config["dropdown_selector"])
                if not dropdown:
                    continue

                for sub_node in dropdown.css(config["level2_selector"]):
                    sub_link = sub_node.css_first("a")
                    if not sub_link:
                        continue

                    sub_name = sub_link.text(strip=True)
                    sub_url  = sub_link.attributes.get("href", "")

                    if "voir" in sub_name.lower() or "all" in sub_name.lower():
                        continue

                    if sub_url and not sub_url.startswith("http"):
                        sub_url = base_url + sub_url

                    if sub_url:
                        categories_raw.append({
                            "boutique":       boutique,
                            "rayon":          rayon_name,
                            "sous_categorie": sub_name,
                            "url":            sub_url,
                        })

        except Exception as e:
            logger.error(f"[sync_urls] Erreur {boutique} : {e}")

    result = _deduplicate_categories(categories_raw)
    logger.info(f"[sync_urls] {boutique} : {len(result)} catégories trouvées")
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Sync URLs : Mytek — REST API + curl_cffi (remplace Playwright)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_mytek_category_tree(
    node: dict,
    result: List[Dict],
    parent_name: str = "",
    parent_slug: str = "",
):
    """
    Parse récursivement l'arbre des catégories retourné par
    /rest/V1/categories et construit la liste des catégories.

    Magento 2 retourne un arbre avec :
      - id, parent_id, name, is_active, position, level
      - children_data (ou children) : liste des sous-catégories
    """
    name = node.get("name", "")
    cat_id = node.get("id")
    children = node.get("children_data") or node.get("children") or []
    is_active = node.get("is_active", True)

    # Ignorer la racine (id <= 2) et les catégories inactives
    if not name or not cat_id or int(cat_id) <= 2 or not is_active:
        for child in children:
            _parse_mytek_category_tree(child, result, parent_name, parent_slug)
        return

    slug = _slugify(name)

    if parent_name:
        # Construire l'URL (convention Magento : parent-slug/child-slug.html)
        url = f"https://www.mytek.tn/{parent_slug}/{slug}.html"

        result.append({
            "boutique":       "Mytek",
            "rayon":          parent_name,
            "sous_categorie": name,
            "url":            url,
        })

    # Descendre dans les enfants
    for child in children:
        _parse_mytek_category_tree(child, result, name, slug)


def _parse_mytek_menu_html(tree, result: List[Dict]):
    """
    Parse le menu vertical de Mytek depuis le HTML de la homepage.
    Fallback si la REST API n'est pas accessible.
    """
    # Sélecteurs pour le menu vertical Mytek
    rayon_selectors = [
        "ul.vertical-list > li.rootverticalnav",
        "li.level0.nav-item",
        "nav ul.menu > li",
    ]

    for rayon_sel in rayon_selectors:
        rayon_nodes = tree.css(rayon_sel)
        if not rayon_nodes:
            continue

        for rayon_node in rayon_nodes:
            # Nom du rayon
            rayon_name = ""
            name_tag = rayon_node.css_first(
                "span.main-category-name, a.level-top span, a.level-top"
            )
            if name_tag:
                rayon_name = name_tag.text(strip=True)
            if not rayon_name:
                a_tag = rayon_node.css_first("a")
                if a_tag:
                    rayon_name = a_tag.text(strip=True)

            if not rayon_name or len(rayon_name) < 2:
                continue

            # Liens de sous-catégories
            submenu_selectors = [
                "div.vertical_fullwidthmenu",
                "div.mega-menu",
                "ul.level0",
                "div.submenu",
            ]

            links = []
            for sub_sel in submenu_selectors:
                submenu = rayon_node.css_first(sub_sel)
                if submenu:
                    links = submenu.css("a[href]")
                    break

            if not links:
                # Prendre tous les liens du rayon
                links = rayon_node.css("a[href]")

            for link in links:
                href = link.attributes.get("href", "")
                sub_name = link.text(strip=True)

                if not href or not sub_name:
                    continue
                if "javascript:" in href:
                    continue
                if len(sub_name) < 2:
                    continue
                if any(
                    skip in sub_name.lower()
                    for skip in ("voir", "all", "tout", "découvrir")
                ):
                    continue

                if not href.startswith("http"):
                    href = "https://www.mytek.tn" + href

                # Ne garder que les URLs de catégories
                if ".html" in href or "/catalog/category" in href:
                    result.append({
                        "boutique":       "Mytek",
                        "rayon":          rayon_name,
                        "sous_categorie": sub_name,
                        "url":            href,
                    })
        break  # Un seul sélecteur suffit s'il marche


async def _fetch_mytek_categories() -> List[Dict]:
    """
    Scrape les catégories Mytek via :
      1) Magento REST API /rest/V1/categories (priorité — contourne Cloudflare)
      2) curl_cffi HTML de la homepage (fallback)
    """
    categories_raw: List[Dict] = []

    # ── Stratégie 1 : REST API ──────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(
            timeout=20.0, headers=HEADERS_MYTEK_API
        ) as client:
            r = await client.get(f"{MYTEK_REST_BASE}/categories")

            if r.status_code == 200:
                tree = r.json()
                _parse_mytek_category_tree(tree, categories_raw)

                if categories_raw:
                    logger.info(
                        f"[sync_urls] Mytek REST API : "
                        f"{len(categories_raw)} catégories trouvées"
                    )
                else:
                    logger.warning(
                        "[sync_urls] Mytek REST API : arbre renvoyé vide"
                    )
            elif r.status_code == 401:
                logger.warning(
                    "[sync_urls] Mytek REST API : protégée par token (401)"
                )
            else:
                logger.warning(
                    f"[sync_urls] Mytek REST API : HTTP {r.status_code}"
                )

    except Exception as e:
        logger.warning(f"[sync_urls] Mytek REST API échouée : {e}")

    if categories_raw:
        return _deduplicate_categories(categories_raw)

    # ── Stratégie 2 : curl_cffi HTML ────────────────────────────────────────
    logger.info("[sync_urls] Mytek : fallback vers curl_cffi HTML…")
    try:
        async with AsyncSession(
            impersonate="chrome124", verify=False, timeout=20
        ) as client:
            r = await client.get(
                "https://www.mytek.tn/", headers=HEADERS_MYTEK_HTML
            )

            if r.status_code == 200 and "Just a moment" not in r.text:
                tree = selectolax.parser.HTMLParser(r.text)
                _parse_mytek_menu_html(tree, categories_raw)

                if categories_raw:
                    logger.info(
                        f"[sync_urls] Mytek HTML : "
                        f"{len(categories_raw)} catégories trouvées"
                    )
                else:
                    logger.warning(
                        "[sync_urls] Mytek HTML : menu vide ou non détecté"
                    )
            else:
                logger.warning(
                    f"[sync_urls] Mytek HTML bloqué par Cloudflare "
                    f"(HTTP {r.status_code})"
                )

    except Exception as e:
        logger.warning(f"[sync_urls] Mytek HTML échoué : {e}")

    result = _deduplicate_categories(categories_raw)
    logger.info(f"[sync_urls] Mytek : {len(result)} catégories uniques")
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Tâche de sync URLs
# ══════════════════════════════════════════════════════════════════════════════

def _run_sync_urls_task(task_id: str) -> None:
    db: Session = SessionLocal()
    try:
        crud.update_task_status(db, task_id, TaskStatus.RUNNING)
        logger.info(f"[service] Sync URLs démarré — tâche {task_id[:8]}")

        async def _gather():
            results = await asyncio.gather(
                _fetch_html_categories("Spacenet"),
                _fetch_html_categories("Tunisianet"),
                _fetch_mytek_categories(),
                return_exceptions=True,
            )
            all_cats: List[Dict] = []
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"[sync_urls] Erreur dans gather : {r}")
                else:
                    all_cats.extend(r)
            return all_cats

        all_categories = asyncio.run(_gather())

        result = crud.upsert_category_urls(db, all_categories)

        crud.update_task_status(
            db, task_id,
            status         = TaskStatus.DONE,
            total_scraped  = len(all_categories),
            total_inserted = result["inserted"],
            total_updated  = result["updated"],
        )
        logger.info(
            f"[service] Sync URLs terminé — {len(all_categories)} catégories "
            f"({result['inserted']} nouvelles, {result['updated']} mises à jour)"
        )

    except Exception as e:
        logger.error(f"[service] Sync URLs échoué : {e}", exc_info=True)
        crud.update_task_status(
            db, task_id,
            status        = TaskStatus.FAILED,
            error_message = str(e),
        )
    finally:
        db.close()
        _cancel_flags.pop(task_id, None)


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIE 2 : Scraping de produits depuis les CategoryUrl en DB
# ══════════════════════════════════════════════════════════════════════════════

def _run_scrape_task(
    task_id:    str,
    site:       str,
    rayons:     Optional[List[str]],
    max_pages:  int,
) -> None:
    db: Session = SessionLocal()
    try:
        crud.update_task_status(db, task_id, TaskStatus.RUNNING)
        logger.info(f"[service] Scraping produits démarré — tâche {task_id[:8]} ({site})")

        total_scraped  = 0
        total_inserted = 0
        total_updated  = 0

        if site == "all":
            boutiques = ["Spacenet", "Tunisianet", "Mytek"]
        else:
            label_map = {
                "spacenet":   "Spacenet",
                "tunisianet": "Tunisianet",
                "mytek":      "Mytek",
            }
            boutiques = [label_map.get(site, site)]

        for boutique_label in boutiques:

            if _is_cancelled(task_id):
                logger.info(f"[service] Tâche {task_id[:8]} annulée avant {boutique_label}")
                break

            site_key = boutique_label.lower()
            cat_urls = crud.get_category_urls(
                db,
                boutique=boutique_label,
                active_only=True,
            )

            if rayons:
                cat_urls = [c for c in cat_urls if c.rayon in rayons]

            if not cat_urls:
                logger.warning(
                    f"[service] Aucune URL active pour {boutique_label}. "
                    f"Lancez d'abord POST /scrape/sync-urls."
                )
                continue

            logger.info(f"[service] {boutique_label} : {len(cat_urls)} catégories à scraper")

            ScraperClass = SCRAPERS.get(site_key)
            if not ScraperClass:
                logger.error(f"[service] Scraper inconnu : {site_key}")
                continue

            scraper = ScraperClass()

            cat_dicts = [
                {
                    "id":             c.id,
                    "boutique":       c.boutique,
                    "rayon":          c.rayon,
                    "sous_categorie": c.sous_categorie,
                    "url":            c.url,
                }
                for c in cat_urls
            ]

            def make_callback(tid):
                def progress_callback(count):
                    if _is_cancelled(tid):
                        raise InterruptedError(f"Tâche {tid[:8]} annulée")
                return progress_callback

            try:
                products = scraper.scrape_urls(
                    category_urls=cat_dicts,
                    max_pages=max_pages,
                    progress_callback=make_callback(task_id),
                )
            except InterruptedError:
                logger.info(f"[service] Tâche {task_id[:8]} interrompue pendant {boutique_label}")
                products = []

            total_scraped += len(products)

            if products:
                result = crud.upsert_products(db, products)
                total_inserted += result["inserted"]
                total_updated  += result["updated"]
                logger.info(
                    f"[service] {boutique_label} : {result['inserted']} insérés, "
                    f"{result['updated']} mis à jour"
                )

                scraped_cat_ids = {p["category_url_id"] for p in products if p.get("category_url_id")}
                for cat_id in scraped_cat_ids:
                    crud.mark_category_scraped(db, cat_id)

            if _is_cancelled(task_id):
                break

        if _is_cancelled(task_id):
            crud.update_task_status(
                db, task_id,
                status         = TaskStatus.FAILED,
                total_scraped  = total_scraped,
                total_inserted = total_inserted,
                total_updated  = total_updated,
                error_message  = "Arrêté manuellement",
            )
        else:
            crud.update_task_status(
                db, task_id,
                status         = TaskStatus.DONE,
                total_scraped  = total_scraped,
                total_inserted = total_inserted,
                total_updated  = total_updated,
            )
            logger.info(
                f"[service] Tâche {task_id[:8]} terminée : "
                f"{total_scraped} scrappés, {total_inserted} insérés, {total_updated} mis à jour"
            )

    except Exception as e:
        logger.error(f"[service] Tâche {task_id[:8]} échouée : {e}", exc_info=True)
        crud.update_task_status(
            db, task_id,
            status        = TaskStatus.FAILED,
            error_message = str(e),
        )
    finally:
        db.close()
        _cancel_flags.pop(task_id, None)


# ══════════════════════════════════════════════════════════════════════════════
#  API publique du service
# ══════════════════════════════════════════════════════════════════════════════

def start_sync_urls_task(db: Session) -> str:
    task_id = str(uuid.uuid4())
    _cancel_flags[task_id] = threading.Event()
    crud.create_task(db, task_id=task_id, site="sync-urls", categories=None)
    executor.submit(_run_sync_urls_task, task_id)
    logger.info(f"[service] Sync URLs soumis : {task_id[:8]}")
    return task_id


def start_scrape_task(
    db:         Session,
    site:       str,
    categories: Optional[List[str]],
    max_pages:  int,
) -> str:
    task_id = str(uuid.uuid4())
    _cancel_flags[task_id] = threading.Event()
    crud.create_task(db, task_id=task_id, site=site, categories=categories)
    executor.submit(_run_scrape_task, task_id, site, categories, max_pages)
    logger.info(f"[service] Scraping soumis : {task_id[:8]} ({site})")
    return task_id


def cancel_scrape_task(task_id: str) -> bool:
    flag = _cancel_flags.get(task_id)
    if flag is None:
        return False
    flag.set()
    logger.info(f"[service] Annulation demandée pour {task_id[:8]}")
    return True


def get_available_categories(site: str) -> Optional[List[str]]:
    label_map = {
        "spacenet":   "Spacenet",
        "tunisianet": "Tunisianet",
        "mytek":      "Mytek",
    }
    boutique = label_map.get(site)
    if not boutique:
        return None

    db = SessionLocal()
    try:
        cats = crud.get_category_urls(db, boutique=boutique, active_only=True)
        rayons = sorted(set(c.rayon for c in cats))
        return rayons
    finally:
        db.close()