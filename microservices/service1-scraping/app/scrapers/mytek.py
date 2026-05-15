"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scrapers/mytek.py  –  Mytek.tn
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Technologie : Playwright async + selectolax
  Mytek charge ses produits via JavaScript (Magento).
  On utilise Playwright pour exécuter le JS, puis
  selectolax pour parser le HTML rendu.

  Pagination : ?p=1, ?p=2, …
  Fin : page vide OU nb produits < seuil.
"""

import asyncio
import time
import logging
from typing import List, Dict, Optional

import selectolax.parser
from playwright.async_api import async_playwright, Browser

from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.mytek.tn"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CONTENEUR = "div.product-container"
SEL_NOM   = ".product-item-link"
SEL_PRIX  = "span.final-price"
SEL_IMAGE = "img"

# Seuil bas : si une page a moins de ce nb de produits → c'est la dernière
PAGE_MIN_PRODUCTS = 12


class MytekScraper(BaseScraper):
    @property
    def site_name(self) -> str:
        return "mytek"

    @property
    def boutique_label(self) -> str:
        return "Mytek"

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

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=UA,
                locale="fr-FR",
            )

            try:
                for page_num in range(1, max_pages + 1):
                    # Construction de l'URL paginée
                    if page_num == 1:
                        page_url = url
                    else:
                        separator = "&" if "?" in url else "?"
                        page_url = f"{url}{separator}p={page_num}"

                    logger.debug(f"[mytek] {sous_categorie} — page {page_num}")

                    page = await context.new_page()

                    # Bloquer images/polices pour aller plus vite
                    await page.route(
                        "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,eot}",
                        lambda route: route.abort(),
                    )

                    try:
                        await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

                        # Attendre les conteneurs produits
                        try:
                            await page.wait_for_selector(CONTENEUR, timeout=15000)
                        except Exception:
                            pass

                        # Attendre les prix si disponibles
                        try:
                            await page.wait_for_selector(SEL_PRIX, timeout=8000)
                        except Exception:
                            await asyncio.sleep(0.5)

                        html = await page.content()
                    finally:
                        await page.close()

                    tree  = selectolax.parser.HTMLParser(html)
                    nodes = tree.css(CONTENEUR)

                    if not nodes:
                        logger.info(f"[mytek] {sous_categorie} : aucun produit page {page_num}, arrêt")
                        break

                    # Détection dernière page (Mytek répète la dernière page)
                    first_node = nodes[0].css_first(SEL_NOM)
                    if first_node:
                        current_first = first_node.text(strip=True)
                        if last_first and current_first == last_first:
                            logger.info(f"[mytek] {sous_categorie} : dernière page à {page_num-1}")
                            break
                        last_first = current_first

                    page_products: List[Dict] = []
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

                        page_products.append({
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

                    produits.extend(page_products)

                    if progress_callback:
                        progress_callback(len(produits))

                    logger.info(
                        f"[mytek] {sous_categorie} page {page_num} : {len(page_products)} produits"
                    )

                    # Fin si page sous le seuil minimum
                    if len(page_products) < PAGE_MIN_PRODUCTS:
                        break

                    await asyncio.sleep(0.3)

            finally:
                await context.close()
                await browser.close()

        logger.info(f"[mytek] {sous_categorie} : {len(produits)} produits au total")
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
