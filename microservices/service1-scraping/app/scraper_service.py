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
import os
import gc
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

MYTEK_REST_BASE = "https://www.mytek.tn/rest/V1"
MYTEK_PROXY     = os.environ.get("MYTEK_PROXY", "")

UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS_MYTEK_HTML = {
    "User-Agent": UA_CHROME,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.mytek.tn/",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

HEADERS_MYTEK_API = {
    "User-Agent": UA_CHROME,
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

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

    seen   = set()
    unique = []
    for item in categories_raw:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    logger.info(f"[sync_urls] {boutique} : {len(unique)} catégories trouvées")
    return unique


# ══════════════════════════════════════════════════════════════════════════════
#  _fetch_mytek_categories  —  curl_cffi + API REST Magento
# ══════════════════════════════════════════════════════════════════════════════

def _make_mytek_session() -> AsyncSession:
    proxy = MYTEK_PROXY if MYTEK_PROXY else None
    return AsyncSession(
        impersonate="chrome124",
        verify=False,
        timeout=20,
        proxies={"http": proxy, "https": proxy} if proxy else None,
    )


async def _fetch_mytek_via_rest_api() -> Optional[List[Dict]]:
    logger.info("[mytek REST] Récupération des catégories via API Magento...")
    categories: List[Dict] = []

    async with _make_mytek_session() as client:
        try:
            r = await client.get(
                f"{MYTEK_REST_BASE}/categories?rootCategoryId=2",
                headers=HEADERS_MYTEK_API,
                timeout=15,
            )
            logger.info(f"[mytek REST] /categories → HTTP {r.status_code}")

            if r.status_code == 401:
                logger.info("[mytek REST] API protégée par token, abandon.")
                return None

            if r.status_code != 200:
                logger.info(f"[mytek REST] Erreur {r.status_code}, abandon.")
                return None

            data = r.json()

        except Exception as e:
            logger.warning(f"[mytek REST] Exception : {e}")
            return None

    def _parse_category_tree(node, parent_name: str = "") -> None:
        name      = node.get("name", "").strip()
        cat_id    = node.get("id")
        level     = node.get("level", 0)
        is_active = node.get("is_active", False)
        children  = node.get("children_data", [])

        if not name or not is_active or level < 2:
            for child in children:
                _parse_category_tree(child, parent_name)
            return

        url_key = ""
        for attr in node.get("custom_attributes", []):
            if attr.get("attribute_code") == "url_key":
                url_key = attr.get("value", "")
                break
        if not url_key and name:
            url_key = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")

        if level == 2:
            rayon = name
            for child in children:
                _parse_category_tree(child, rayon)
        else:
            rayon = parent_name or "Divers"
            if url_key:
                cat_url = f"https://www.mytek.tn/{url_key}.html"
                categories.append({
                    "boutique":       "Mytek",
                    "rayon":          rayon,
                    "sous_categorie": name,
                    "url":            cat_url,
                })
            for child in children:
                _parse_category_tree(child, rayon)

    _parse_category_tree(data)

    if not categories:
        logger.warning("[mytek REST] Aucune catégorie extraite depuis l'arbre.")
        return None

    seen   = set()
    unique = []
    for item in categories:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    logger.info(f"[mytek REST] {len(unique)} catégories uniques trouvées.")
    return unique


async def _fetch_mytek_via_html() -> List[Dict]:
    logger.info("[mytek HTML] Fallback scraping HTML de la homepage Mytek...")
    categories_raw: List[Dict] = []

    async with _make_mytek_session() as client:
        try:
            r = await client.get(
                "https://www.mytek.tn",
                headers=HEADERS_MYTEK_HTML,
                timeout=20,
            )
            logger.info(f"[mytek HTML] Homepage → HTTP {r.status_code}")

            if r.status_code == 403 or "Just a moment" in r.text or "Checking your browser" in r.text:
                logger.warning("[mytek HTML] Cloudflare actif, impossible de scraper la homepage.")
                return []

            if r.status_code != 200:
                return []

            tree = selectolax.parser.HTMLParser(r.text)

            rayon_items = tree.css("ul.vertical-list > li.rootverticalnav")
            if not rayon_items:
                rayon_items = tree.css("nav li.level0, ul.nav-sections li.level0")

            logger.info(f"[mytek HTML] {len(rayon_items)} rayons détectés dans le HTML.")

            for rayon_node in rayon_items:
                rayon_name = ""
                for sel in ["span.main-category-name", "span.menu-title", "a > span", "a"]:
                    n = rayon_node.css_first(sel)
                    if n:
                        rayon_name = n.text(strip=True)
                        if rayon_name:
                            break

                if not rayon_name or len(rayon_name) < 2:
                    continue

                submenu = rayon_node.css_first("div.vertical_fullwidthmenu, div.submenu, ul.level1")
                if not submenu:
                    continue

                for link in submenu.css("a.title-normale, ul.level1 > li > a, div.grid-item-6 a"):
                    href     = link.attributes.get("href", "")
                    sub_name = link.text(strip=True)

                    if not href or "javascript:" in href or not sub_name:
                        continue
                    if "voir" in sub_name.lower() or len(sub_name) < 2:
                        continue

                    if not href.startswith("http"):
                        href = "https://www.mytek.tn" + href

                    categories_raw.append({
                        "boutique":       "Mytek",
                        "rayon":          rayon_name,
                        "sous_categorie": sub_name,
                        "url":            href,
                    })

        except Exception as e:
            logger.error(f"[mytek HTML] Exception : {e}")

    seen   = set()
    unique = []
    for item in categories_raw:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    logger.info(f"[mytek HTML] {len(unique)} catégories uniques trouvées.")
    return unique


async def _fetch_mytek_categories() -> List[Dict]:
    result = await _fetch_mytek_via_rest_api()
    if result:
        logger.info(f"[mytek] Catégories obtenues via REST API ({len(result)} entrées).")
        return result

    logger.info("[mytek] Fallback vers scraping HTML...")
    result = await _fetch_mytek_via_html()
    if result:
        logger.info(f"[mytek] Catégories obtenues via HTML ({len(result)} entrées).")
        return result

    logger.error("[mytek] Impossible de récupérer les catégories (toutes les stratégies ont échoué).")
    return []


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIE 2 : Task sync URLs
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
#  PARTIE 3 : Scraping de produits (TRAITEMENT SITE PAR SITE)
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

            # ── Étape 1 : Scrape le site complet ──
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

            # ── Étape 2 : Upsert en base de données pour CE SITE ──
            if products:
                logger.info(f"[service] {boutique_label} : Début upsert en base de {len(products)} produits...")
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

                # ── Étape 3 : Libération explicite de la mémoire (CRUCIAL POUR RENDER) ──
                del products
                del scraped_cat_ids
                gc.collect()
                logger.info(f"[service] {boutique_label} : Mémoire nettoyée, passage au site suivant.")
            else:
                logger.info(f"[service] {boutique_label} : Aucun produit scrapé.")

            if _is_cancelled(task_id):
                break

        # Mise à jour du statut global de la tâche
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