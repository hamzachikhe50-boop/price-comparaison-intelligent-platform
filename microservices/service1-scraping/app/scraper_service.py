"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scraper_service.py  –  Orchestration du scraping
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Deux flux principaux :

  1. SYNC URLS (urls.py)
     POST /scrape/sync-urls
     → Lance un worker qui scrape les menus des 3 sites
       via urls.py (httpx + selectolax) et stocke les
       CategoryUrl en base de données.

  2. SCRAPE PRODUCTS
     POST /scrape/start
     → Lit les CategoryUrl actives depuis la DB,
       les distribue aux scrapers (Spacenet, Tunisianet,
       Mytek) et stocke les produits avec upsert.
"""

import uuid
import asyncio
import logging
import threading
import time
import base64 # Ajouté pour la capture d'écran dans les logs
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async # Ajouté pour contourner Cloudflare

import httpx
import selectolax.parser

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
#  PARTIE 1 : Sync des URLs de catégories depuis les 3 sites (urls.py logic)
# ══════════════════════════════════════════════════════════════════════════════

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

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


async def _fetch_html_categories(boutique: str) -> List[Dict]:
    """
    Scrape les catégories d'un site HTML statique (Spacenet ou Tunisianet)
    en utilisant httpx + selectolax, exactement comme dans urls.py.
    """
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

    # Dédoublonnage par URL
    seen   = set()
    unique = []
    for item in categories_raw:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    logger.info(f"[sync_urls] {boutique} : {len(unique)} catégories trouvées")
    return unique


async def _fetch_mytek_categories() -> List[Dict]:
    """
    Scrape le menu de Mytek en forçant l'affichage GLOBAL via CSS injection
    et en utilisant Stealth pour contourner les protections anti-bots.
    """
    categories_raw: List[Dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
        )

        try:
            page = await context.new_page()
            
            # AJOUT IMPORTANT : Rendre Playwright indétectable (contourne Cloudflare)
            await stealth_async(page)
            
            # Bloquer images/polices pour accélérer le chargement sur Render
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )

            try:
                logger.info("Navigation vers https://www.mytek.tn ...")
                await page.goto("https://www.mytek.tn", wait_until="networkidle", timeout=45000)

                # Gérer les cookies
                try:
                    await asyncio.sleep(1)
                    accept_btn = page.locator("button:has-text('Accepter'), button:has-text('Tout'), .cc-btn")
                    if await accept_btn.count() > 0:
                        await accept_btn.first.click(timeout=2000)
                except Exception:
                    pass

                # --- SOLUTION "NUCLÉAIRE" : Injection de style CSS global ---
                logger.info("Injection CSS globale pour forcer la visibilité du menu...")
                await page.evaluate("""
                    () => {
                        const style = document.createElement('style');
                        style.innerHTML = `
                            ul.vertical-list, li.rootverticalnav, div.vertical_fullwidthmenu, div.root-col-1, div.grid-item-6, a.title-normale {
                                display: block !important; visibility: visible !important; opacity: 1 !important;
                                height: auto !important; width: auto !important; position: static !important;
                                overflow: visible !important; top: auto !important; left: auto !important;
                            }
                        `;
                        document.head.appendChild(style);
                    }
                """)
                
                await asyncio.sleep(1)

                # Attendre EXPLICITEMENT que le menu soit là
                try:
                    await page.wait_for_selector("ul.vertical-list > li.rootverticalnav", timeout=15000)
                    rayon_items = await page.locator("ul.vertical-list > li.rootverticalnav").all()
                except Exception as e:
                    logger.error(f"Le menu de Mytek n'a pas été trouvé à temps.")
                    # Capture d'écran en Base64 pour la lire directement dans les logs de Render
                    screenshot_bytes = await page.screenshot()
                    b64_image = base64.b64encode(screenshot_bytes).decode('utf-8')
                    logger.error(f"VOIR CAPTURE (copier-coller cette ligne dans un navigateur) : data:image/png;base64,{b64_image}")
                    rayon_items = []

                logger.info(f"{len(rayon_items)} rayons détectés.")

                for index, item in enumerate(rayon_items):
                    try:
                        rayon_html = await item.inner_html()
                        tree = selectolax.parser.HTMLParser(rayon_html)
                        
                        has_content = tree.css_first("div.grid-item-6") is not None

                        if not has_content:
                            try:
                                await item.hover(timeout=2000)
                                await asyncio.sleep(1.5) 
                                rayon_html = await item.inner_html()
                                tree = selectolax.parser.HTMLParser(rayon_html)
                            except Exception as hover_err:
                                logger.warning(f"Hover impossible pour l'item {index}, on utilise le HTML statique: {hover_err}")

                        # Nom du rayon
                        name_tag = tree.css_first("span.main-category-name")
                        rayon_name = "Rayon Inconnu"
                        if name_tag:
                            rayon_name = name_tag.text(strip=True)
                        
                        if not rayon_name or len(rayon_name) < 2:
                            continue

                        # Parsing des liens
                        submenu = tree.css_first("div.vertical_fullwidthmenu")
                        if submenu:
                            count_grid = 0
                            for grid_item in submenu.css("div.grid-item-6"):
                                link = grid_item.css_first("a.title-normale")
                                if not link:
                                    link = grid_item.css_first("a")

                                if link:
                                    href = link.attrs.get("href", "")
                                    sub_cat_name = link.text(strip=True)

                                    if href and "javascript:" not in href and sub_cat_name:
                                        if not href.startswith("http"):
                                            href = "https://www.mytek.tn" + href

                                        categories_raw.append({
                                            "boutique":       "Mytek",
                                            "rayon":          rayon_name,
                                            "sous_categorie": sub_cat_name,
                                            "url":            href,
                                        })
                                        count_grid += 1
                            
                            if count_grid > 0:
                                logger.info(f"Traité : {rayon_name} ({count_grid} urls trouvées)")

                    except Exception as e:
                        logger.warning(f"Erreur rayon {index}: {e}")
                        continue

            finally:
                await page.close()

        finally:
            await context.close()
            await browser.close()

    # Dédoublonnage
    seen = set()
    unique = []
    for item in categories_raw:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    logger.info(f"[sync_urls] Mytek : {len(unique)} catégories uniques trouvées")
    return unique


def _run_sync_urls_task(task_id: str) -> None:
    """
    Tâche en arrière-plan : scrape les menus des 3 sites et
    stocke les CategoryUrl en base de données.
    """
    db: Session = SessionLocal()
    try:
        crud.update_task_status(db, task_id, TaskStatus.RUNNING)
        logger.info(f"[service] Sync URLs démarré — tâche {task_id[:8]}")

        # Lancer les 3 scrapers de menu en async
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

        # Sauvegarder en DB
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
    """
    Tâche en arrière-plan : lit les CategoryUrl depuis la DB,
    scrape les produits page par page et les upsert.

    site    : "mytek" | "spacenet" | "tunisianet" | "all"
    rayons  : liste de rayons à filtrer, ou None (= tous)
    """
    db: Session = SessionLocal()
    try:
        crud.update_task_status(db, task_id, TaskStatus.RUNNING)
        logger.info(f"[service] Scraping produits démarré — tâche {task_id[:8]} ({site})")

        total_scraped  = 0
        total_inserted = 0
        total_updated  = 0

        # Déterminer quels sites scraper
        if site == "all":
            boutiques = ["Spacenet", "Tunisianet", "Mytek"]
        else:
            # Mapper nom technique → label DB
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

            # Récupérer les URLs actives pour ce site
            site_key = boutique_label.lower()
            cat_urls = crud.get_category_urls(
                db,
                boutique=boutique_label,
                active_only=True,
            )

            # Filtrer par rayon si demandé
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

            # Convertir les ORM en dicts pour le scraper
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

                # Marquer les catégories comme scrappées
                scraped_cat_ids = {p["category_url_id"] for p in products if p.get("category_url_id")}
                for cat_id in scraped_cat_ids:
                    crud.mark_category_scraped(db, cat_id)

            if _is_cancelled(task_id):
                break

        # Statut final
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
    """
    Lance la synchronisation des URLs de catégories en arrière-plan.
    Retourne le task_id immédiatement.
    """
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
    """
    Lance un scraping de produits en arrière-plan.
    categories ici = liste de rayons (ex: ["Informatique", "Téléphonie"]).
    Retourne le task_id immédiatement.
    """
    task_id = str(uuid.uuid4())
    _cancel_flags[task_id] = threading.Event()
    crud.create_task(db, task_id=task_id, site=site, categories=categories)
    executor.submit(_run_scrape_task, task_id, site, categories, max_pages)
    logger.info(f"[service] Scraping soumis : {task_id[:8]} ({site})")
    return task_id


def cancel_scrape_task(task_id: str) -> bool:
    """
    Demande l'annulation d'une tâche.
    Retourne True si la tâche existait, False sinon.
    """
    flag = _cancel_flags.get(task_id)
    if flag is None:
        return False
    flag.set()
    logger.info(f"[service] Annulation demandée pour {task_id[:8]}")
    return True


def get_available_categories(site: str) -> Optional[List[str]]:
    """
    Retourne les rayons disponibles pour un site (depuis la DB).
    """
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