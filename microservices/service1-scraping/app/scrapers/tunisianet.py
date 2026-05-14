"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scrapers/tunisianet.py  –  Tunisianet.com.tn
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Technologie : httpx async + selectolax
  Tunisianet est SSR (PrestaShop) — pas besoin de JS.

  Pagination : ?page=1&order=product.price.asc
  Fin : page vide OU premier produit identique.
"""

import asyncio
import time
import logging
from typing import List, Dict, Optional

import httpx
import selectolax.parser

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tunisianet.com.tn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

CONTENEUR = "article.product-miniature"
SEL_NOM   = "h2.h3.product-title a"
SEL_PRIX  = "span.price"
SEL_IMAGE = "img"
SEL_NEXT  = "a.next[href]"


class TunisianetScraper(BaseScraper):

    @property
    def site_name(self) -> str:
        return "tunisianet"

    @property
    def boutique_label(self) -> str:
        return "Tunisianet"

    # ── Méthode async interne ─────────────────────────────────────────────────

    async def _scrape_async(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int,
        progress_callback=None,
    ) -> List[Dict]:
        produits: List[Dict] = []
        last_first: Optional[str] = None

        async with httpx.AsyncClient(
            timeout=20.0,
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            for page_num in range(1, max_pages + 1):
                if page_num == 1:
                    page_url = f"{url}?order=product.price.asc"
                else:
                    page_url = f"{url}?page={page_num}&order=product.price.asc"

                logger.debug(f"[tunisianet] {sous_categorie} — page {page_num}")

                try:
                    r = await client.get(page_url)
                    if r.status_code != 200:
                        logger.warning(f"[tunisianet] HTTP {r.status_code} sur {page_url}")
                        break
                except Exception as e:
                    logger.error(f"[tunisianet] Erreur réseau page {page_num} : {e}")
                    break

                tree  = selectolax.parser.HTMLParser(r.text)
                nodes = tree.css(CONTENEUR)

                if not nodes:
                    logger.info(f"[tunisianet] {sous_categorie} : aucun produit page {page_num}, arrêt")
                    break

                # Détection dernière page
                first_node = nodes[0].css_first(SEL_NOM)
                if first_node:
                    current_first = first_node.text(strip=True)
                    if last_first and current_first == last_first:
                        logger.info(f"[tunisianet] {sous_categorie} : dernière page à {page_num-1}")
                        break
                    last_first = current_first

                for node in nodes:
                    nom_node  = node.css_first(SEL_NOM)
                    prix_node = node.css_first(SEL_PRIX)
                    if not nom_node or not prix_node:
                        continue

                    nom  = nom_node.text(strip=True)
                    prix = prix_node.text(strip=True)
                    lien = nom_node.attributes.get("href", "")
                    if lien and not lien.startswith("http"):
                        lien = BASE_URL + lien

                    img_node = node.css_first(SEL_IMAGE)
                    img_src  = ""
                    if img_node:
                        img_src = (
                            img_node.attributes.get("data-src", "")
                            or img_node.attributes.get("src", "")
                        )
                        if img_src.startswith("data:"):
                            img_src = ""
                        elif img_src.startswith("//"):
                            img_src = "https:" + img_src
                        elif img_src and not img_src.startswith("http"):
                            img_src = BASE_URL + img_src

                    produits.append({
                        "nom":             nom,
                        "prix":            prix,
                        "image":           img_src,
                        "lien":            lien,
                        "boutique":        self.boutique_label,
                        "categorie":       sous_categorie,
                        "rayon":           rayon,
                        "sous_categorie":  sous_categorie,
                        "category_url_id": category_url_id,
                    })

                if progress_callback:
                    progress_callback(len(produits))

                if not tree.css_first(SEL_NEXT):
                    break

                await asyncio.sleep(0.3)

        logger.info(f"[tunisianet] {sous_categorie} : {len(produits)} produits")
        return produits

    # ── Interface synchrone (pont sync → async) ───────────────────────────────

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
