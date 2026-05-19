"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scrapers/mytek.py  –  Mytek.tn
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Technologie : curl_cffi (impersonate Chrome) + API REST Magento
  Stratégie   :
    1. API REST Magento /rest/V1/categories  → liste des catégories
       (ne passe pas par le WAF Cloudflare)
    2. Fallback scraping HTML curl_cffi si l'API est protégée
       (même logique que scraper_service.py temps réel)

  PAS de Playwright — compatible Render.com (pas de Chromium).
"""

import asyncio
import re
import time
import logging
import os
from typing import List, Dict, Optional

import selectolax.parser
from curl_cffi.requests import AsyncSession

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL       = "https://www.mytek.tn"
MYTEK_REST_BASE = "https://www.mytek.tn/rest/V1"
MYTEK_PROXY    = os.environ.get("MYTEK_PROXY", "")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS_HTML = {
    "User-Agent": UA,
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

HEADERS_API = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Seuil bas : si une page a moins de ce nb de produits → c'est la dernière
PAGE_MIN_PRODUCTS = 12
PAGE_SIZE_REST    = 20

# Sélecteurs HTML (fallback scraping)
CONTENEUR = "div.product-container"
SEL_NOM   = ".product-item-link"
SEL_PRIX  = "span.final-price, span.special-price span.price, span.price-wrapper span.price, span.price"
SEL_IMAGE = "img"

CONFIGS_FALLBACK = [
    {
        "conteneur": "ol.products li.item",
        "nom": "a.product-item-link",
        "prix": "span.price",
        "image": "img.product-image-photo",
        "ref": "div.value[itemprop='sku']",
    },
    {
        "conteneur": "div.product-container",
        "nom": "a.product-item-link, h2 a, .product-name a",
        "prix": "span.final-price, span.special-price span.price, span.price-wrapper span.price, .price-box .price",
        "image": "img",
        "ref": "div.value[itemprop='sku'], .product-meta .sku",
    },
    {
        "conteneur": "div.products div.product-item",
        "nom": "a.product-item-link",
        "prix": "span.special-price span.price, span.price-wrapper span.price, span.price",
        "image": "img.product-image-photo",
        "ref": "div.value[itemprop='sku']",
    },
]


def _make_curl_session() -> AsyncSession:
    proxy = MYTEK_PROXY if MYTEK_PROXY else None
    return AsyncSession(
        impersonate="chrome124",
        verify=False,
        timeout=25,
        proxies={"http": proxy, "https": proxy} if proxy else None,
    )


def _extraire_produits_html(tree, page_num: int, temps_scrape: float, sous_categorie: str, rayon: str, category_url_id: int) -> List[Dict]:
    """Parse le HTML rendu et retourne les produits trouvés."""
    for config in CONFIGS_FALLBACK:
        conteneurs = tree.css(config["conteneur"])
        if not conteneurs:
            continue
        produits = []
        for node in conteneurs:
            nom, lien, prix = "", "", ""
            for sel in config["nom"].split(", "):
                n = node.css_first(sel.strip())
                if n:
                    nom  = n.text(strip=True)
                    lien = n.attributes.get("href", "")
                    break
            for sel in config["prix"].split(", "):
                p = node.css_first(sel.strip())
                if p:
                    prix = p.text(strip=True)
                    break
            if not nom or not prix:
                continue

            img_src  = ""
            img_node = node.css_first(config["image"])
            if img_node:
                for attr in ["data-src", "data-lazy-src", "src"]:
                    val = img_node.attributes.get(attr, "")
                    if val and not val.startswith("data:"):
                        img_src = val
                        break
                if img_src.startswith("//"):
                    img_src = "https:" + img_src
                elif img_src and not img_src.startswith("http"):
                    img_src = BASE_URL + img_src

            ref      = ""
            ref_node = node.css_first(config["ref"])
            if ref_node:
                ref = re.sub(r"[\[\]]", "", ref_node.text(strip=True)).strip()

            if lien and not lien.startswith("http"):
                lien = BASE_URL + lien

            produits.append({
                "nom":             nom,
                "prix":            prix,
                "image":           img_src,
                "lien":            lien,
                "boutique":        "Mytek",
                "categorie":       sous_categorie,
                "rayon":           rayon,
                "sous_categorie":  sous_categorie,
                "category_url_id": category_url_id,
                "reference":       ref,
                "description":     "",
            })
        if produits:
            return produits
    return []


class MytekScraper(BaseScraper):
    @property
    def site_name(self) -> str:
        return "mytek"

    @property
    def boutique_label(self) -> str:
        return "Mytek"

    # ── Stratégie 1 : API REST Magento ────────────────────────────────────────

    async def _scrape_via_rest_api(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int,
        progress_callback=None,
    ) -> Optional[List[Dict]]:
        """
        Utilise l'endpoint REST Magento /rest/V1/products avec un filtre
        sur l'URL key de la catégorie pour récupérer les produits.
        Retourne None si l'API est protégée ou inaccessible.
        """
        # Extraire l'url_key depuis l'URL de catégorie Mytek
        # Ex: https://www.mytek.tn/informatique/ecrans.html → "ecrans"
        url_key_match = re.search(r"/([^/]+)\.html$", url)
        if not url_key_match:
            logger.debug(f"[mytek REST] URL non reconnue : {url}")
            return None

        url_key = url_key_match.group(1)
        logger.debug(f"[mytek REST] url_key={url_key} pour {sous_categorie}")

        produits: List[Dict] = []

        async with _make_curl_session() as client:
            # Étape 1 : récupérer l'ID de la catégorie par url_key
            try:
                r = await client.get(
                    f"{MYTEK_REST_BASE}/categories?searchCriteria[filterGroups][0][filters][0][field]=url_key"
                    f"&searchCriteria[filterGroups][0][filters][0][value]={url_key}",
                    headers=HEADERS_API,
                    timeout=10,
                )
                if r.status_code == 401:
                    logger.info("[mytek REST] API protégée par token, abandon.")
                    return None
                if r.status_code != 200:
                    logger.info(f"[mytek REST] HTTP {r.status_code} sur catégories, abandon.")
                    return None

                data = r.json()
                items = data.get("items", [])
                if not items:
                    logger.info(f"[mytek REST] Catégorie '{url_key}' introuvable via API.")
                    return None

                category_id = items[0].get("id")
                if not category_id:
                    return None

                logger.info(f"[mytek REST] Catégorie '{sous_categorie}' → id={category_id}")

            except Exception as e:
                logger.warning(f"[mytek REST] Erreur catégorie lookup : {e}")
                return None

            # Étape 2 : paginer les produits de la catégorie
            for page_num in range(1, max_pages + 1):
                start = time.time()
                params = (
                    f"searchCriteria[filterGroups][0][filters][0][field]=category_id"
                    f"&searchCriteria[filterGroups][0][filters][0][value]={category_id}"
                    f"&searchCriteria[filterGroups][0][filters][0][conditionType]=eq"
                    f"&searchCriteria[pageSize]={PAGE_SIZE_REST}"
                    f"&searchCriteria[currentPage]={page_num}"
                    f"&fields=items[id,sku,name,price,custom_attributes,media_gallery_entries]"
                )
                try:
                    r = await client.get(
                        f"{MYTEK_REST_BASE}/products?{params}",
                        headers=HEADERS_API,
                        timeout=15,
                    )
                    if r.status_code == 401:
                        logger.info("[mytek REST] API protégée par token.")
                        return None if not produits else produits
                    if r.status_code != 200:
                        break

                    data  = r.json()
                    items = data.get("items", [])
                    if not items:
                        break

                    temps_scrape = round(time.time() - start, 2)
                    for item in items:
                        attrs    = {a["attribute_code"]: a["value"] for a in item.get("custom_attributes", [])}
                        gallery  = item.get("media_gallery_entries", [])
                        img_src  = ""
                        if gallery:
                            img_src = f"https://www.mytek.tn/pub/media/catalog/product{gallery[0].get('file', '')}"
                        prix     = item.get("price", "")
                        prix_str = f"{prix} TND" if prix else ""
                        url_k    = attrs.get("url_key", "")
                        lien     = f"https://www.mytek.tn/{url_k}.html" if url_k else ""

                        produits.append({
                            "nom":             item.get("name", ""),
                            "prix":            prix_str,
                            "image":           img_src,
                            "lien":            lien,
                            "boutique":        "Mytek",
                            "categorie":       sous_categorie,
                            "rayon":           rayon,
                            "sous_categorie":  sous_categorie,
                            "category_url_id": category_url_id,
                            "reference":       item.get("sku", ""),
                            "description":     attrs.get("short_description", ""),
                        })

                    if progress_callback:
                        progress_callback(len(produits))

                    logger.info(f"[mytek REST] {sous_categorie} P{page_num}: {len(items)} produits ({temps_scrape}s)")

                    if len(items) < PAGE_SIZE_REST:
                        break

                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.warning(f"[mytek REST] Exception page {page_num}: {e}")
                    break

        return produits if produits else None

    # ── Stratégie 2 : Scraping HTML via curl_cffi ─────────────────────────────

    async def _scrape_via_html(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Scraping HTML classique via curl_cffi (impersonate Chrome).
        Mytek charge les produits côté serveur pour les pages de catégorie
        (contrairement à la recherche qui est JS-heavy).
        """
        logger.info(f"[mytek HTML] Fallback HTML pour '{sous_categorie}'")
        produits: List[Dict] = []
        last_first: Optional[str] = None

        async with _make_curl_session() as client:
            # Warmup : visite homepage pour initialiser les cookies
            try:
                await client.get(BASE_URL, headers=HEADERS_HTML, timeout=10)
            except Exception:
                pass

            for page_num in range(1, max_pages + 1):
                start = time.time()
                sep      = "&" if "?" in url else "?"
                page_url = url if page_num == 1 else f"{url}{sep}p={page_num}"

                try:
                    r = await client.get(page_url, headers=HEADERS_HTML, timeout=20)
                    logger.debug(f"[mytek HTML] {sous_categorie} P{page_num} → HTTP {r.status_code}")

                    if r.status_code == 403 or "Just a moment" in r.text or "Checking your browser" in r.text:
                        logger.warning(f"[mytek HTML] Cloudflare bloqué sur '{sous_categorie}'")
                        break

                    if r.status_code != 200:
                        break

                    tree         = selectolax.parser.HTMLParser(r.text)
                    temps_scrape = round(time.time() - start, 2)

                    # Détection fin de pagination (Mytek répète la dernière page)
                    first_node = tree.css_first(f"{CONTENEUR} {SEL_NOM}")
                    if first_node:
                        current_first = first_node.text(strip=True)
                        if last_first and current_first == last_first:
                            logger.info(f"[mytek HTML] Dernière page atteinte à P{page_num - 1}")
                            break
                        last_first = current_first

                    page_products = _extraire_produits_html(
                        tree, page_num, temps_scrape, sous_categorie, rayon, category_url_id
                    )

                    if not page_products:
                        logger.info(f"[mytek HTML] Aucun produit page {page_num}, arrêt")
                        break

                    produits.extend(page_products)

                    if progress_callback:
                        progress_callback(len(produits))

                    logger.info(f"[mytek HTML] {sous_categorie} P{page_num}: {len(page_products)} produits ({temps_scrape}s)")

                    if len(page_products) < PAGE_MIN_PRODUCTS:
                        break

                    await asyncio.sleep(0.4)

                except Exception as e:
                    logger.warning(f"[mytek HTML] Exception P{page_num}: {e}")
                    break

        return produits

    # ── Orchestrateur async : REST → HTML ─────────────────────────────────────

    async def _scrape_async(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int,
        progress_callback=None,
    ) -> List[Dict]:

        # Stratégie 1 : API REST Magento (rapide, contourne Cloudflare)
        produits = await self._scrape_via_rest_api(
            category_url_id, rayon, sous_categorie, url, max_pages, progress_callback
        )
        if produits is not None:
            logger.info(f"[mytek] '{sous_categorie}' : {len(produits)} produits via REST API")
            return produits

        # Stratégie 2 : HTML scraping curl_cffi
        produits = await self._scrape_via_html(
            category_url_id, rayon, sous_categorie, url, max_pages, progress_callback
        )
        logger.info(f"[mytek] '{sous_categorie}' : {len(produits)} produits via HTML")
        return produits

    # ── Interface synchrone ───────────────────────────────────────────────────

    def scrape_category_url(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int = 100,
        progress_callback=None,
    ) -> List[Dict]:
        return asyncio.run(
            self._scrape_async(
                category_url_id, rayon, sous_categorie, url, max_pages, progress_callback
            )
        )