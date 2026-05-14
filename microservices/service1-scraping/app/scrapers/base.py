"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  scrapers/base.py  –  Classe abstraite commune
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Chaque scraper reçoit maintenant une liste de
  CategoryUrl (boutique, rayon, sous_cat, url)
  au lieu de catégories hardcodées.

  Technologie : selectolax (HTMLParser rapide)
  pour les sites HTML statiques (Spacenet, Tunisianet)
  et Playwright async pour Mytek (JavaScript).
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Classe de base pour tous les scrapers.
    L'interface principale est scrape_urls() qui accepte
    une liste de dicts {boutique, rayon, sous_categorie, url, id}.
    """

    @property
    @abstractmethod
    def site_name(self) -> str:
        """Identifiant technique minuscule : 'mytek', 'spacenet', 'tunisianet'"""
        pass

    @property
    @abstractmethod
    def boutique_label(self) -> str:
        """Nom affiché : 'Mytek', 'Spacenet', 'Tunisianet'"""
        pass

    @abstractmethod
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
        Scrape tous les produits d'une URL de catégorie.

        Chaque produit retourné doit contenir :
            {
                "nom":              str,
                "prix":             str,
                "image":            str | None,
                "lien":             str,
                "boutique":         str,
                "categorie":        str,   # = sous_categorie
                "rayon":            str,
                "sous_categorie":   str,
                "category_url_id":  int,
            }
        """
        pass

    def scrape_urls(
        self,
        category_urls: List[Dict],
        max_pages: int = 100,
        progress_callback=None,
    ) -> List[Dict]:
        """
        Scrape une liste d'URLs de catégories en séquence.

        category_urls : liste de dicts avec les clés
            id, boutique, rayon, sous_categorie, url
        """
        all_products: List[Dict] = []

        for cat in category_urls:
            cat_id         = cat.get("id", 0)
            rayon          = cat.get("rayon", "")
            sous_categorie = cat.get("sous_categorie", "")
            url            = cat.get("url", "")

            if not url:
                continue

            logger.info(f"[{self.site_name}] ► {rayon} / {sous_categorie} — {url}")
            try:
                products = self.scrape_category_url(
                    category_url_id=cat_id,
                    rayon=rayon,
                    sous_categorie=sous_categorie,
                    url=url,
                    max_pages=max_pages,
                    progress_callback=progress_callback,
                )
                all_products.extend(products)
                logger.info(
                    f"[{self.site_name}] ✓ {sous_categorie} : {len(products)} produits"
                )
            except Exception as e:
                logger.error(
                    f"[{self.site_name}] ✗ Erreur sur '{sous_categorie}' ({url}) : {e}"
                )

            # Pause entre deux catégories
            time.sleep(1)

        logger.info(
            f"[{self.site_name}] Scraping terminé : {len(all_products)} produits au total"
        )
        return all_products
