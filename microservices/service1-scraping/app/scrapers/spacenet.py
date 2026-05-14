"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scrapers/spacenet.py  –  Spacenet.tn
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Technologie : httpx (sync) + selectolax
  Spacenet utilise PrestaShop SSR — pas besoin de JS.

  Pagination : ?page=1, ?page=2, …
  Fin de pagination : page vide OU premier produit
                      identique à la page précédente.
"""

import time
import logging
from typing import List, Dict, Optional

import httpx
import selectolax.parser

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://spacenet.tn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Sélecteurs CSS pour Spacenet (PrestaShop)
CONTENEUR  = "div.field-product-item.item-inner.product-miniature.js-product-miniature"
SEL_NOM    = "h2.product_name a"
SEL_PRIX   = "span.price"
SEL_IMAGE  = "img.img-responsive.product_image"
SEL_NEXT   = "a.next[href]"


class SpacenetScraper(BaseScraper):

    @property
    def site_name(self) -> str:
        return "spacenet"

    @property
    def boutique_label(self) -> str:
        return "Spacenet"

    def scrape_category_url(
        self,
        category_url_id: int,
        rayon: str,
        sous_categorie: str,
        url: str,
        max_pages: int = 100,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Scrape toutes les pages d'une catégorie Spacenet.
        Utilise httpx synchrone + selectolax pour parser le HTML.
        """
        produits: List[Dict] = []
        last_first: Optional[str] = None

        with httpx.Client(
            timeout=20.0,
            headers=HEADERS,
            follow_redirects=True,
        ) as client:
            for page_num in range(1, max_pages + 1):
                # Construction de l'URL paginée
                page_url = url if page_num == 1 else f"{url}?page={page_num}"
                logger.debug(f"[spacenet] {sous_categorie} — page {page_num} — {page_url}")

                try:
                    r = client.get(page_url)
                    if r.status_code != 200:
                        logger.warning(f"[spacenet] HTTP {r.status_code} sur {page_url}")
                        break
                except Exception as e:
                    logger.error(f"[spacenet] Erreur réseau page {page_num} : {e}")
                    break

                tree  = selectolax.parser.HTMLParser(r.text)
                nodes = tree.css(CONTENEUR)

                if not nodes:
                    logger.info(f"[spacenet] {sous_categorie} : aucun produit page {page_num}, arrêt")
                    break

                # Détection dernière page : premier produit identique
                first_node = nodes[0].css_first(SEL_NOM)
                if first_node:
                    current_first = first_node.text(strip=True)
                    if last_first and current_first == last_first:
                        logger.info(f"[spacenet] {sous_categorie} : dernière page détectée à {page_num-1}")
                        break
                    last_first = current_first

                for node in nodes:
                    nom_node   = node.css_first(SEL_NOM)
                    prix_node  = node.css_first(SEL_PRIX)
                    if not nom_node or not prix_node:
                        continue

                    nom  = nom_node.text(strip=True)
                    prix = prix_node.text(strip=True)
                    lien = nom_node.attributes.get("href", "")
                    if lien and not lien.startswith("http"):
                        lien = BASE_URL + lien

                    # Image : préférer data-src (lazy loading) puis src
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

                # Vérifier s'il existe une page suivante
                if not tree.css_first(SEL_NEXT):
                    break

                time.sleep(0.3)

        logger.info(f"[spacenet] {sous_categorie} : {len(produits)} produits")
        return produits
