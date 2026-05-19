"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scrapers/mytek.py  –  Mytek.tn
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Technologie : curl_cffi + Magento REST API + selectolax
  ─────────────────────────────────────────────────────
  Stratégie 1 (prioritaire) : REST API Magento
    → /rest/V1/products?searchCriteria[filterGroups]...
    → Contourne Cloudflare (les endpoints /rest/V1/ ne passent
      généralement pas par le WAF)
    → Retourne du JSON structuré (pas de parsing HTML)

  Stratégie 2 (fallback) : curl_cffi HTML scraping
    → Requête HTTP avec empreinte TLS Chrome (impersonate)
    → Parsing HTML avec selectolax
    → Peut être bloqué par Cloudflare JS challenge

  Pagination REST API : currentPage + pageSize
  Pagination HTML     : ?p=1, ?p=2, …
"""

import asyncio
import re
import time
import logging
import unicodedata
from typing import List, Dict, Optional, Tuple

import httpx
import selectolax.parser
from curl_cffi.requests import AsyncSession

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.mytek.tn"
MYTEK_REST_BASE = "https://www.mytek.tn/rest/V1"

# ── Headers pour HTML scraping (curl_cffi) ────────────────────────────────────
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
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.mytek.tn/",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# ── Headers pour REST API ─────────────────────────────────────────────────────
HEADERS_MYTEK_API = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
}

# ── Configs CSS pour parsing HTML (fallback) ──────────────────────────────────
CONFIGS_MYTEK_HTML = [
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
        "prix": (
            "span.final-price, span.special-price span.price, "
            "span.price-wrapper span.price, .price-box .price"
        ),
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

PAGE_MIN_PRODUCTS = 12
REST_API_PAGE_SIZE = 50


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(name: str) -> str:
    """Convertit un nom en slug URL (convention Magento)."""
    slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = slug.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def _strip_html(html_str: str) -> str:
    """Supprime les balises HTML d'une chaîne."""
    return re.sub(r"<[^>]+>", "", html_str).strip()


# ══════════════════════════════════════════════════════════════════════════════
#  MytekScraper
# ══════════════════════════════════════════════════════════════════════════════

class MytekScraper(BaseScraper):
    """Scraper Mytek : REST API (priorité) + curl_cffi HTML (fallback)."""

    @property
    def site_name(self) -> str:
        return "mytek"

    @property
    def boutique_label(self) -> str:
        return "Mytek"

    # ── Cache de l'arbre des catégories (partagé entre tous les appels) ──────
    _category_name_to_id: Optional[Dict[str, int]] = None
    _category_tree_loaded: bool = False

    # ─────────────────────────────────────────────────────────────────────────
    #  Chargement de l'arbre des catégories (REST API)
    # ─────────────────────────────────────────────────────────────────────────

    async def _ensure_category_tree(self) -> Dict[str, int]:
        """
        Récupère l'arbre complet des catégories via /rest/V1/categories.
        Construit un mapping {nom_catégorie → category_id}.
        Le cache est statique (un seul appel par processus).
        """
        if MytekScraper._category_tree_loaded:
            return MytekScraper._category_name_to_id or {}

        mapping: Dict[str, int] = {}
        try:
            async with httpx.AsyncClient(
                timeout=20.0, headers=HEADERS_MYTEK_API
            ) as client:
                r = await client.get(f"{MYTEK_REST_BASE}/categories")
                if r.status_code == 200:
                    tree = r.json()
                    self._build_name_mapping(tree, mapping, parent_name="")
                    logger.info(
                        f"[mytek] Arbre catégories REST API chargé : "
                        f"{len(mapping)} entrées"
                    )
                else:
                    logger.warning(
                        f"[mytek] REST API catégories : HTTP {r.status_code}"
                    )
        except Exception as e:
            logger.warning(f"[mytek] REST API catégories échouée : {e}")

        MytekScraper._category_name_to_id = mapping
        MytekScraper._category_tree_loaded = True
        return mapping

    def _build_name_mapping(
        self, node: dict, mapping: Dict[str, int], parent_name: str
    ):
        """Parse récursivement l'arbre des catégories Magento."""
        name = node.get("name", "")
        cat_id = node.get("id")
        # Magento 2 utilise "children_data" ou "children"
        children = node.get("children_data") or node.get("children") or []
        is_active = node.get("is_active", True)

        # Skip la racine (id <= 2) et les catégories inactives
        if not name or not cat_id or int(cat_id) <= 2 or not is_active:
            for child in children:
                self._build_name_mapping(child, mapping, parent_name)
            return

        if parent_name:
            # Clé composite (rayon + sous-catégorie) pour matcher précisément
            composite_key = f"{parent_name}::{name}"
            mapping[composite_key] = int(cat_id)
            # Clé simple (sous-catégorie seule) pour fallback
            if name not in mapping:
                mapping[name] = int(cat_id)

        for child in children:
            self._build_name_mapping(child, mapping, name)

    def _find_category_id(self, rayon: str, sous_categorie: str) -> Optional[int]:
        """Cherche le category_id Magento à partir du rayon et sous-catégorie."""
        if not MytekScraper._category_name_to_id:
            return None

        # 1) Match exact rayon + sous-catégorie
        composite = f"{rayon}::{sous_categorie}"
        if composite in MytekScraper._category_name_to_id:
            return MytekScraper._category_name_to_id[composite]

        # 2) Match par sous-catégorie seule
        if sous_categorie in MytekScraper._category_name_to_id:
            return MytekScraper._category_name_to_id[sous_categorie]

        # 3) Match insensible à la casse
        for key, cid in MytekScraper._category_name_to_id.items():
            if key.lower() == sous_categorie.lower():
                return cid
            if key.lower() == composite.lower():
                return cid

        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  Stratégie 1 : REST API Magento
    # ─────────────────────────────────────────────────────────────────────────

    async def _scrape_via_rest_api(
        self,
        category_id: int,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        max_pages: int,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Scrape les produits via /rest/V1/products avec filtre category_id.
        Contourne Cloudflare car les endpoints API ne passent pas par le WAF.
        """
        produits: List[Dict] = []

        async with httpx.AsyncClient(
            timeout=20.0, headers=HEADERS_MYTEK_API
        ) as client:
            for page_num in range(1, max_pages + 1):
                params = (
                    f"searchCriteria[filterGroups][0][filters][0][field]=category_id"
                    f"&searchCriteria[filterGroups][0][filters][0][value]={category_id}"
                    f"&searchCriteria[filterGroups][0][filters][0][conditionType]=eq"
                    f"&searchCriteria[pageSize]={REST_API_PAGE_SIZE}"
                    f"&searchCriteria[currentPage]={page_num}"
                    f"&fields=items[id,sku,name,price,custom_attributes,"
                    f"media_gallery_entries]"
                )
                url = f"{MYTEK_REST_BASE}/products?{params}"

                try:
                    r = await client.get(url)
                    logger.debug(
                        f"[mytek REST] {sous_categorie} page {page_num} → "
                        f"HTTP {r.status_code}"
                    )

                    if r.status_code == 401:
                        logger.warning(
                            "[mytek REST] API protégée par token, abandon."
                        )
                        return produits

                    if r.status_code != 200:
                        logger.warning(
                            f"[mytek REST] HTTP {r.status_code}, arrêt."
                        )
                        break

                    data = r.json()
                    items = data.get("items", [])

                    if not items:
                        logger.debug(
                            f"[mytek REST] {sous_categorie} page {page_num} vide,"
                            f" fin pagination."
                        )
                        break

                    for item in items:
                        produit = self._parse_rest_api_product(
                            item, category_url_id, rayon, sous_categorie
                        )
                        if produit:
                            produits.append(produit)

                    if progress_callback:
                        progress_callback(len(produits))

                    logger.info(
                        f"[mytek REST] {sous_categorie} page {page_num} : "
                        f"{len(items)} produits"
                    )

                    if len(items) < REST_API_PAGE_SIZE:
                        break  # Dernière page

                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.warning(
                        f"[mytek REST] Exception page {page_num} : {e}"
                    )
                    break

        return produits

    def _parse_rest_api_product(
        self,
        item: dict,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
    ) -> Optional[Dict]:
        """Transforme un item REST API en dict produit standard."""
        nom = item.get("name", "")
        if not nom:
            return None

        # ── Custom attributes ──
        attrs = {}
        for a in item.get("custom_attributes", []):
            if "attribute_code" in a and "value" in a:
                attrs[a["attribute_code"]] = a["value"]

        # ── Prix ──
        prix_val = item.get("price", "")
        prix_str = f"{prix_val} TND" if prix_val else ""
        # Certains Magento retournent un dict avec "final_price"
        if isinstance(prix_val, dict):
            fp = prix_val.get("final_price") or prix_val.get("base_price", "")
            prix_str = f"{fp} TND" if fp else ""

        # ── Image ──
        img_src = ""
        gallery = item.get("media_gallery_entries", [])
        if gallery and isinstance(gallery, list):
            entry = gallery[0]
            if isinstance(entry, dict):
                file_path = entry.get("file", "")
                if file_path:
                    img_src = (
                        f"https://www.mytek.tn/pub/media/catalog/product"
                        f"{file_path}"
                    )

        # Fallback : construire l'URL image à partir du thumbnail
        if not img_src:
            thumbnail = attrs.get("thumbnail", "")
            if thumbnail and thumbnail != "no_selection":
                img_src = (
                    f"https://www.mytek.tn/pub/media/catalog/product"
                    f"{thumbnail}"
                )

        # ── Lien produit ──
        url_key = attrs.get("url_key", "")
        lien = f"https://www.mytek.tn/{url_key}.html" if url_key else ""

        # ── Description ──
        description = attrs.get("short_description", "")
        if description:
            description = _strip_html(description)

        # ── Référence / SKU ──
        reference = item.get("sku", "")

        return {
            "nom": nom,
            "prix": prix_str,
            "image": img_src,
            "lien": lien,
            "boutique": "Mytek",
            "categorie": sous_categorie,
            "rayon": rayon,
            "sous_categorie": sous_categorie,
            "category_url_id": category_url_id,
            "reference": reference,
            "description": description,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Stratégie 2 : curl_cffi HTML scraping
    # ─────────────────────────────────────────────────────────────────────────

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
        Scrape les produits via requêtes HTML avec curl_cffi.
        curl_cffi utilise l'empreinte TLS de Chrome pour contourner
        certaines protections Cloudflare (mais pas les challenges JS).
        """
        produits: List[Dict] = []
        last_first_nom: Optional[str] = None

        async with AsyncSession(
            impersonate="chrome124", verify=False, timeout=20
        ) as client:
            for page_num in range(1, max_pages + 1):
                # Construction URL paginée
                if page_num == 1:
                    page_url = url
                else:
                    separator = "&" if "?" in url else "?"
                    page_url = f"{url}{separator}p={page_num}"

                try:
                    r = await client.get(
                        page_url, headers=HEADERS_MYTEK_HTML
                    )

                    # Vérification Cloudflare
                    if r.status_code == 403 or "Just a moment" in r.text:
                        logger.warning(
                            f"[mytek HTML] Bloqué par Cloudflare "
                            f"(HTTP {r.status_code})"
                        )
                        break

                    if r.status_code != 200:
                        logger.debug(
                            f"[mytek HTML] HTTP {r.status_code}, arrêt."
                        )
                        break

                    tree = selectolax.parser.HTMLParser(r.text)
                    page_products = self._extract_products_from_html(
                        tree, category_url_id, rayon, sous_categorie
                    )

                    if not page_products:
                        break

                    # Détection dernière page (Mytek répète la dernière page)
                    first_nom = page_products[0]["nom"]
                    if last_first_nom and first_nom == last_first_nom:
                        logger.debug(
                            f"[mytek HTML] Dernière page atteinte à "
                            f"page {page_num - 1}"
                        )
                        break
                    last_first_nom = first_nom

                    produits.extend(page_products)

                    if progress_callback:
                        progress_callback(len(produits))

                    logger.info(
                        f"[mytek HTML] {sous_categorie} page {page_num} : "
                        f"{len(page_products)} produits"
                    )

                    if len(page_products) < PAGE_MIN_PRODUCTS:
                        break

                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.warning(
                        f"[mytek HTML] Exception page {page_num} : {e}"
                    )
                    break

        return produits

    def _extract_products_from_html(
        self,
        tree,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
    ) -> List[Dict]:
        """Extrait les produits du HTML avec les configs CSS multiples."""
        for config in CONFIGS_MYTEK_HTML:
            conteneurs = tree.css(config["conteneur"])
            if not conteneurs:
                continue

            produits = []
            for node in conteneurs:
                nom, lien, prix = "", "", ""

                # Nom + lien
                for sel in config["nom"].split(", "):
                    n = node.css_first(sel.strip())
                    if n:
                        nom = n.text(strip=True)
                        lien = n.attributes.get("href", "")
                        break

                # Prix
                for sel in config["prix"].split(", "):
                    p = node.css_first(sel.strip())
                    if p:
                        prix = p.text(strip=True)
                        break

                if not nom or not prix:
                    continue

                # Image
                img_src = ""
                img_node = node.css_first(config["image"])
                if img_node:
                    for attr in ("data-src", "data-lazy-src", "src"):
                        val = img_node.attributes.get(attr, "")
                        if val and not val.startswith("data:"):
                            img_src = val
                            break
                    if img_src.startswith("//"):
                        img_src = "https:" + img_src
                    elif img_src and not img_src.startswith("http"):
                        img_src = BASE_URL + img_src

                # Lien absolu
                if lien and not lien.startswith("http"):
                    lien = BASE_URL + lien

                # Référence
                ref = ""
                ref_node = node.css_first(config["ref"])
                if ref_node:
                    ref = re.sub(
                        r"[\[\]]", "", ref_node.text(strip=True)
                    ).strip()

                produits.append({
                    "nom": nom,
                    "prix": prix,
                    "image": img_src,
                    "lien": lien,
                    "boutique": "Mytek",
                    "categorie": sous_categorie,
                    "rayon": rayon,
                    "sous_categorie": sous_categorie,
                    "category_url_id": category_url_id,
                    "reference": ref,
                    "description": "",
                })

            if produits:
                return produits

        return []

    # ─────────────────────────────────────────────────────────────────────────
    #  Orchestrateur async
    # ─────────────────────────────────────────────────────────────────────────

    async def _scrape_async(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int,
        progress_callback=None,
    ) -> List[Dict]:
        """Try REST API first, then curl_cffi HTML."""

        # Charger l'arbre des catégories (une seule fois)
        await self._ensure_category_tree()

        # ── Stratégie 1 : REST API ──
        cat_id = self._find_category_id(rayon, sous_categorie)
        if cat_id:
            logger.info(
                f"[mytek] 🔵 REST API pour '{sous_categorie}' "
                f"(cat_id={cat_id})"
            )
            produits = await self._scrape_via_rest_api(
                cat_id, category_url_id, rayon, sous_categorie,
                max_pages, progress_callback,
            )
            if produits:
                logger.info(
                    f"[mytek] ✅ REST API : {len(produits)} produits "
                    f"pour '{sous_categorie}'"
                )
                return produits
            logger.warning(
                f"[mytek] REST API n'a rien retourné pour '{sous_categorie}'"
            )
        else:
            logger.warning(
                f"[mytek] Pas de category_id trouvé pour "
                f"'{rayon} → {sous_categorie}'"
            )

        # ── Stratégie 2 : curl_cffi HTML ──
        logger.info(f"[mytek] 🟡 Fallback HTML pour '{sous_categorie}'")
        produits = await self._scrape_via_html(
            category_url_id, rayon, sous_categorie, url,
            max_pages, progress_callback,
        )
        if produits:
            logger.info(
                f"[mytek] ✅ HTML : {len(produits)} produits "
                f"pour '{sous_categorie}'"
            )
            return produits

        logger.warning(
            f"[mytek] 🛑 Aucun produit trouvé pour '{sous_categorie}'"
        )
        return []

    # ─────────────────────────────────────────────────────────────────────────
    #  Orchestrateur batch (surcharge scrape_urls pour efficacité)
    # ─────────────────────────────────────────────────────────────────────────

    async def _scrape_all_async(
        self,
        category_urls: List[Dict],
        max_pages: int,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Scrape toutes les catégories avec un seul event loop.
        L'arbre des catégories est chargé une seule fois.
        """
        await self._ensure_category_tree()

        all_produits: List[Dict] = []
        for cat in category_urls:
            produits = await self._scrape_async(
                category_url_id=cat["id"],
                rayon=cat["rayon"],
                sous_categorie=cat["sous_categorie"],
                url=cat["url"],
                max_pages=max_pages,
                progress_callback=progress_callback,
            )
            all_produits.extend(produits)

        return all_produits

    # ─────────────────────────────────────────────────────────────────────────
    #  Interface synchrone (compatible BaseScraper)
    # ─────────────────────────────────────────────────────────────────────────

    def scrape_category_url(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int = 100,
        progress_callback=None,
    ) -> List[Dict]:
        """Scrape une seule catégorie (interface synchrone)."""
        return asyncio.run(
            self._scrape_async(
                category_url_id, rayon, sous_categorie,
                url, max_pages, progress_callback,
            )
        )

    def scrape_urls(
        self,
        category_urls: List[Dict],
        max_pages: int = 100,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Scrape toutes les catégories.
        Surcharge pour charger l'arbre REST API une seule fois.
        """
        return asyncio.run(
            self._scrape_all_async(category_urls, max_pages, progress_callback)
        )

    @classmethod
    def reset_cache(cls):
        """Réinitialise le cache de l'arbre des catégories."""
        cls._category_name_to_id = None
        cls._category_tree_loaded = False