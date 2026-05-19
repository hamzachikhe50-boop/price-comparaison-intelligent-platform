import sys
import re
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import selectolax.parser
import asyncio
import json
from typing import Optional, Dict, Any, Tuple
import time
import hashlib
import logging

from curl_cffi.requests import AsyncSession

# Import des fonctions du matcher
from matcher import trouver_meilleur_match, grouper_resultats_par_reference

CacheResult = Tuple[list, float]

class CacheManager:
    def __init__(self): self._cache: Dict[str, CacheResult] = {}
    def _generer_cle(self, prefix: str, query: str) -> str:
        return f"{prefix}:{hashlib.md5(query.lower().strip().encode()).hexdigest()}"
    def get(self, prefix: str, query: str, ttl: int = 300) -> Optional[list]:
        cle = self._generer_cle(prefix, query)
        if cle not in self._cache: return None
        donnees, timestamp = self._cache[cle]
        if time.time() - timestamp > ttl: del self._cache[cle]; return None
        return donnees
    def set(self, prefix: str, query: str, donnees: list) -> None: self._cache[self._generer_cle(prefix, query)] = (donnees, time.time())
    def clear(self) -> int: count = len(self._cache); self._cache.clear(); return count
    def size(self) -> int: return len(self._cache)
    def cleanup_expired(self, ttl: int = 300) -> int:
        cles_a_supprimer = [cle for cle, (_, timestamp) in self._cache.items() if time.time() - timestamp > ttl]
        for cle in cles_a_supprimer: del self._cache[cle]
        return len(cles_a_supprimer)

resultat_cache = CacheManager()
CACHE_TTL = 300

CONFIGS_HTML = {
    "Spacenet": {
        "url": "https://spacenet.tn/recherche?search_query={query}", "pagination_url": "https://spacenet.tn/recherche?search_query={query}&page={page}",
        "has_next_page": "a.next[href]", "conteneur": "div.field-product-item.item-inner.product-miniature.js-product-miniature",
        "nom": "h2.product_name a", "prix": "span.price", "image": "img.img-responsive.product_image", "lien": "h2.product_name a", "reference": "div.product-reference span"
    },
    "Tunisianet": {
        "url": "https://www.tunisianet.com.tn/recherche?search_query={query}", "pagination_url": "https://www.tunisianet.com.tn/recherche?search_query={query}&page={page}",
        "has_next_page": "a.next[href]", "conteneur": "article.product-miniature",
        "nom": "h2.h3.product-title a", "prix": "span.price", "image": "img", "lien": "h2.h3.product-title a", "reference": "span.product-reference"
    }
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

HEADERS_MYTEK = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
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

MYTEK_PROXY = os.environ.get("MYTEK_PROXY", "")

# ============================================================
#  MYTEK — MAGENTO REST API (contourne Cloudflare)
# ============================================================
MYTEK_REST_BASE = "https://www.mytek.tn/rest/V1"
HEADERS_MYTEK_API = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
}

IMAGE_CACHE = {}
MAX_IMAGE_CACHE = 500

# ============================================================
#  CLIENTS HTTP
# ============================================================
_http_client: Optional[httpx.AsyncClient] = None
_curl_client: Optional[AsyncSession] = None

async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": HEADERS["User-Agent"]}
        )
    return _http_client

async def get_curl_client() -> AsyncSession:
    global _curl_client
    if _curl_client is None:
        proxy = MYTEK_PROXY if MYTEK_PROXY else None
        _curl_client = AsyncSession(
            impersonate="chrome124",
            verify=False,
            timeout=20,
            proxies={"http": proxy, "https": proxy} if proxy else None,
        )
    return _curl_client

async def _mytek_warmup(client: AsyncSession) -> bool:
    """
    Visite la homepage Mytek. 
    Note: curl_cffi ne peut pas résoudre les challenges JS Cloudflare, 
    mais ce warmup permet d'initialiser la session et les cookies de base.
    """
    try:
        print("⏳ [MYTEK WARMUP] Tentative d'accès à la homepage...", flush=True)
        r = await client.get("https://www.mytek.tn/", headers=HEADERS_MYTEK, timeout=15.0)
        print(f"ℹ️ [MYTEK WARMUP] Statut reçu: {r.status_code}", flush=True)
        
        if r.status_code == 200 and "Just a moment" not in r.text:
            print("✅ [MYTEK WARMUP] Homepage accessible (pas de challenge JS).", flush=True)
            return True
        else:
            snippet = r.text[:150].replace('\n', ' ')
            print(f"⚠️ [MYTEK WARMUP] Bloqué ou Challenge Cloudflare détecté. HTML: {snippet}", flush=True)
            return False
    except Exception as e:
        print(f"❌ [MYTEK WARMUP] Erreur: {e}", flush=True)
        return False

async def fetch_missing_details(produit: dict) -> dict:
    lien = produit.get("lien", ""); boutique = produit.get("boutique", "")
    if not lien or not lien.startswith("http"): return {"reference": "", "description": ""}
    try:
        if boutique == "Mytek":
            curl_client = await get_curl_client()
            r = await curl_client.get(lien, headers=HEADERS_MYTEK, timeout=10.0)
            if r.status_code != 200 or "Just a moment" in r.text:
                return {"reference": "", "description": ""}
            html = r.text
        else:
            client = await get_http_client(); r = await client.get(lien, timeout=4.0); html = r.text

        tree = selectolax.parser.HTMLParser(html)
        ref = ""
        for sel in {"Mytek": ["div.card-body div.sku", "div.value[itemprop='sku']"], "Tunisianet": ["span.product-reference"], "Spacenet": [".product-reference span"]}.get(boutique, []):
            node = tree.css_first(sel)
            if node: ref = re.sub(r'[\[\]]', '', node.text(strip=True)).strip(); break
        desc = ""
        for sel in {"Mytek": ["div.search-short-description", "div.product.description"], "Tunisianet": ["div.product-description.rte", "div.rte"], "Spacenet": ["div.product-description", "div.rte"]}.get(boutique, []):
            node = tree.css_first(sel)
            if node and len(node.text(strip=True, separator=" ")) > 20: desc = node.text(strip=True, separator=" "); break
        if not desc:
            meta_node = tree.css_first("meta[name='description']")
            if meta_node: desc = meta_node.attributes.get("content", "").strip()
        return {"reference": ref, "description": desc}
    except: return {"reference": "", "description": ""}

async def scraper_html_worker(queue: asyncio.Queue, client: httpx.AsyncClient, boutique: str, query: str, max_pages: int = 10):
    config = CONFIGS_HTML.get(boutique)
    if not config: return
    base_url = {"Spacenet": "https://spacenet.tn", "Tunisianet": "https://www.tunisianet.com.tn"}.get(boutique, "")
    try:
        for page_num in range(1, max_pages + 1):
            start = time.time()
            url = config["url"].format(query=query) if page_num == 1 else config["pagination_url"].format(query=query, page=page_num)
            r = await client.get(url, headers=HEADERS, timeout=15.0)
            if r.status_code != 200: break
            tree = selectolax.parser.HTMLParser(r.text); temps_scrape = round(time.time() - start, 2)
            produits_page = []
            for node in tree.css(config["conteneur"]):
                n = node.css_first(config["nom"]); p = node.css_first(config["prix"])
                if n and p:
                    img = node.css_first(config["image"]); img_src = ""
                    if img:
                        img_src = img.attributes.get("data-src", "") or img.attributes.get("src", "")
                        if img_src.startswith("data:"): img_src = ""
                        if img_src and img_src.startswith("//"): img_src = "https:" + img_src
                        elif img_src and not img_src.startswith("http"): img_src = base_url + img_src
                    ref = ""
                    if config.get("reference"):
                        ref_node = node.css_first(config["reference"])
                        if ref_node: ref = re.sub(r'[\[\]]', '', ref_node.text(strip=True)).strip()
                    produits_page.append({"nom": n.text(strip=True), "prix": p.text(strip=True), "image": img_src, "lien": n.attributes.get("href", ""), "boutique": boutique, "page": page_num, "temps_scrape": temps_scrape, "reference": ref, "description": ""})
            if not produits_page: break
            await queue.put({"boutique": boutique, "produits": produits_page, "page": page_num, "count": len(produits_page)})
            print(f"📦 {boutique} P{page_num}: {len(produits_page)} produits ({temps_scrape}s)", flush=True)
            if page_num == 1 and not tree.css_first(config["has_next_page"]): break
            await asyncio.sleep(0.2)
    except Exception as e: print(f"❌ Erreur {boutique}: {e}", flush=True)

def _extraire_produits_mytek(tree, page_num, temps_scrape):
    configs = [
        {"conteneur": "ol.products li.item", "nom": "a.product-item-link", "prix": "span.price", "image": "img.product-image-photo", "ref": "div.value[itemprop='sku']"},
        {"conteneur": "div.product-container", "nom": "a.product-item-link, h2 a, .product-name a", "prix": "span.final-price, span.special-price span.price, span.price-wrapper span.price, .price-box .price", "image": "img", "ref": "div.value[itemprop='sku'], .product-meta .sku"},
        {"conteneur": "div.products div.product-item", "nom": "a.product-item-link", "prix": "span.special-price span.price, span.price-wrapper span.price, span.price", "image": "img.product-image-photo", "ref": "div.value[itemprop='sku']"},
    ]
    for config in configs:
        conteneurs = tree.css(config["conteneur"])
        if not conteneurs: continue
        produits = []
        for node in conteneurs:
            nom, lien, prix = "", "", ""
            for sel in config["nom"].split(", "):
                n = node.css_first(sel.strip())
                if n: nom = n.text(strip=True); lien = n.attributes.get("href", ""); break
            for sel in config["prix"].split(", "):
                p = node.css_first(sel.strip())
                if p: prix = p.text(strip=True); break
            if not nom or not prix: continue
            img_src, img_node = "", node.css_first(config["image"])
            if img_node:
                for attr in ["data-src", "data-lazy-src", "src"]:
                    val = img_node.attributes.get(attr, "")
                    if val and not val.startswith("data:"): img_src = val; break
                if img_src.startswith("//"): img_src = "https:" + img_src
                elif img_src and not img_src.startswith("http"): img_src = "https://www.mytek.tn" + img_src
            ref = ""
            ref_node = node.css_first(config["ref"])
            if ref_node: ref = re.sub(r'[\[\]]', '', ref_node.text(strip=True)).strip()
            produits.append({"nom": nom, "prix": prix, "image": img_src, "lien": lien, "boutique": "Mytek", "page": page_num, "temps_scrape": temps_scrape, "reference": ref, "description": ""})
        if produits: return produits
    return []

# ============================================================
#  WORKER MYTEK — STRATÉGIE 1: MAGENTO REST API (sans Cloudflare)
# ============================================================
async def _mytek_via_rest_api(queue: asyncio.Queue, query: str, max_pages: int = 10) -> bool:
    """
    Utilise l'API REST Magento native de Mytek.
    Les endpoints /rest/V1/ ne passent généralement pas par le WAF Cloudflare.
    """
    print(f"🔵 [MYTEK REST] Tentative via API Magento pour: '{query}'", flush=True)
    client = await get_http_client()
    PAGE_SIZE = 20
    produits_trouves = False

    for page_num in range(1, max_pages + 1):
        start = time.time()
        # Magento REST search: filtre sur name + sku, wildcard %query%
        params = (
            f"searchCriteria[filterGroups][0][filters][0][field]=name"
            f"&searchCriteria[filterGroups][0][filters][0][value]=%25{query}%25"
            f"&searchCriteria[filterGroups][0][filters][0][conditionType]=like"
            f"&searchCriteria[pageSize]={PAGE_SIZE}"
            f"&searchCriteria[currentPage]={page_num}"
            f"&fields=items[id,sku,name,price,custom_attributes,media_gallery_entries]"
        )
        url = f"{MYTEK_REST_BASE}/products?{params}"
        try:
            r = await client.get(url, headers=HEADERS_MYTEK_API, timeout=15.0)
            print(f"📥 [MYTEK REST] Page {page_num} → HTTP {r.status_code}", flush=True)

            if r.status_code == 401:
                # Endpoint protégé par token — on abandonne cette stratégie
                print("🔒 [MYTEK REST] API protégée par token, abandon.", flush=True)
                return False

            if r.status_code != 200:
                print(f"❌ [MYTEK REST] Erreur {r.status_code}, abandon.", flush=True)
                return False

            data = r.json()
            items = data.get("items", [])
            if not items:
                print(f"📭 [MYTEK REST] Aucun item page {page_num}, fin pagination.", flush=True)
                break

            temps_scrape = round(time.time() - start, 2)
            produits_page = []
            for item in items:
                # Extraire les custom_attributes utiles
                attrs = {a["attribute_code"]: a["value"] for a in item.get("custom_attributes", [])}
                # Image principale
                img_src = ""
                gallery = item.get("media_gallery_entries", [])
                if gallery:
                    img_src = f"https://www.mytek.tn/pub/media/catalog/product{gallery[0].get('file', '')}"
                # Prix
                prix = item.get("price", "")
                prix_str = f"{prix} TND" if prix else ""
                # URL produit via url_key
                url_key = attrs.get("url_key", "")
                lien = f"https://www.mytek.tn/{url_key}.html" if url_key else ""

                produits_page.append({
                    "nom": item.get("name", ""),
                    "prix": prix_str,
                    "image": img_src,
                    "lien": lien,
                    "boutique": "Mytek",
                    "page": page_num,
                    "temps_scrape": temps_scrape,
                    "reference": item.get("sku", ""),
                    "description": attrs.get("short_description", ""),
                })

            if produits_page:
                produits_trouves = True
                await queue.put({"boutique": "Mytek", "produits": produits_page, "page": page_num, "count": len(produits_page)})
                print(f"📦 [MYTEK REST] P{page_num}: {len(produits_page)} produits ({temps_scrape}s)", flush=True)

            if len(items) < PAGE_SIZE:
                break  # Dernière page
            await asyncio.sleep(0.3)

        except Exception as e:
            print(f"❌ [MYTEK REST] Exception: {e}", flush=True)
            return False

    return produits_trouves


# ============================================================
#  WORKER MYTEK — STRATÉGIE 2: SCRAPING HTML VIA PROXY
# ============================================================
async def _mytek_via_proxy(queue: asyncio.Queue, query: str, max_pages: int = 10) -> bool:
    """
    Scraping HTML classique via un proxy résidentiel (MYTEK_PROXY env var).
    Format attendu: http://user:pass@host:port  ou  socks5://host:port
    """
    if not MYTEK_PROXY:
        print("⚠️ [MYTEK PROXY] Aucun proxy configuré (MYTEK_PROXY vide), abandon.", flush=True)
        return False

    print(f"🟡 [MYTEK PROXY] Tentative via proxy pour: '{query}'", flush=True)
    client = await get_curl_client()
    produits_trouves = False

    for page_num in range(1, max_pages + 1):
        start = time.time()
        if page_num == 1:
            target_url = f"https://www.mytek.tn/catalogsearch/result/?q={query}"
        else:
            target_url = f"https://www.mytek.tn/catalogsearch/result/?q={query}&p={page_num}"

        try:
            r = await client.get(target_url, headers=HEADERS_MYTEK, timeout=20.0)
            print(f"📥 [MYTEK PROXY] Page {page_num} → HTTP {r.status_code}", flush=True)

            if r.status_code == 403 or "Just a moment" in r.text or "Checking your browser" in r.text:
                print("🛑 [MYTEK PROXY] Toujours bloqué malgré le proxy.", flush=True)
                return False

            if r.status_code != 200:
                break

            tree = selectolax.parser.HTMLParser(r.text)
            temps_scrape = round(time.time() - start, 2)
            produits_page = _extraire_produits_mytek(tree, page_num, temps_scrape)

            if not produits_page:
                break

            produits_trouves = True
            await queue.put({"boutique": "Mytek", "produits": produits_page, "page": page_num, "count": len(produits_page)})
            print(f"📦 [MYTEK PROXY] P{page_num}: {len(produits_page)} produits ({temps_scrape}s)", flush=True)

            if len(produits_page) < 25:
                break
            await asyncio.sleep(0.5)

        except Exception as e:
            print(f"❌ [MYTEK PROXY] Exception: {e}", flush=True)
            break

    return produits_trouves


# ============================================================
#  WORKER MYTEK — ORCHESTRATEUR (REST API → Proxy → Abandon)
# ============================================================
async def scraper_mytek_worker(queue: asyncio.Queue, query: str, max_pages: int = 10):
    print(f"🟢 [MYTEK WORKER] Démarrage pour: '{query}'", flush=True)

    # Stratégie 1 : API REST Magento (rapide, sans Cloudflare)
    ok = await _mytek_via_rest_api(queue, query, max_pages)
    if ok:
        print("✅ [MYTEK WORKER] Succès via API REST.", flush=True)
        return

    # Stratégie 2 : Scraping HTML + proxy résidentiel
    print("🔄 [MYTEK WORKER] Fallback → proxy HTML...", flush=True)
    ok = await _mytek_via_proxy(queue, query, max_pages)
    if ok:
        print("✅ [MYTEK WORKER] Succès via proxy.", flush=True)
        return

    print("🛑 [MYTEK WORKER] Toutes les stratégies ont échoué.", flush=True)

# ============================================================
#  FLUX DE RECHERCHE ET COMPARAISON
# ============================================================
async def flux_de_recherche_ordonne(query: str):
    resultat_en_cache = resultat_cache.get("search", query, CACHE_TTL)
    if resultat_en_cache is not None:
        print(f"📋 Cache HIT pour recherche: {query}", flush=True)
        for data in resultat_en_cache: yield f"data: {json.dumps(data)}\n\n"
        yield "data: [DONE]\n\n"; return

    print(f"🔍 Cache MISS pour recherche: {query}", flush=True)
    queue = asyncio.Queue()
    client = await get_http_client()

    workers = [
        asyncio.create_task(scraper_html_worker(queue, client, "Tunisianet", query)),
        asyncio.create_task(scraper_html_worker(queue, client, "Spacenet", query)),
        asyncio.create_task(scraper_mytek_worker(queue, query))
    ]
    tous_les_resultats = []

    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=2.0)
                tous_les_resultats.append(data); yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                if all(w.done() for w in workers): break
                continue
    finally:
        for w in workers:
            if not w.done(): w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    if tous_les_resultats:
        resultat_cache.set("search", query, tous_les_resultats)
        print(f"💾 Résultats mis en cache pour: {query} ({len(tous_les_resultats)} entrées)", flush=True)
    yield "data: [DONE]\n\n"

def parse_prix_py(prix_str):
    if not prix_str: return float('inf')
    clean = re.sub(r'[^0-9.,]', '', prix_str).replace(' ', '').replace(',', '.')
    parts = clean.split('.')
    if len(parts) > 2: clean = parts[0] + ''.join(parts[1:-1]) + '.' + parts[-1]
    try: return float(clean)
    except: return float('inf')

async def flux_compare_stream(query: str):
    resultat_en_cache = resultat_cache.get("compare", query, CACHE_TTL)
    if resultat_en_cache is not None:
        print(f"📋 Cache HIT pour comparaison: {query}", flush=True)
        for data in resultat_en_cache: yield f"data: {json.dumps(data)}\n\n"
        yield "data: [DONE]\n\n"; return

    print(f"🔍 Cache MISS pour comparaison: {query}", flush=True)
    queue = asyncio.Queue()
    client = await get_http_client()

    workers = [
        asyncio.create_task(scraper_html_worker(queue, client, "Tunisianet", query, max_pages=1)),
        asyncio.create_task(scraper_html_worker(queue, client, "Spacenet", query, max_pages=1)),
        asyncio.create_task(scraper_mytek_worker(queue, query, max_pages=1))
    ]
    buffer_par_site = {"Tunisianet": [], "Spacenet": [], "Mytek": []}
    start_time = time.time(); TIMEOUT_COMPARAISON = 30.0

    try:
        while True:
            temps_ecoule = time.time() - start_time
            if temps_ecoule > TIMEOUT_COMPARAISON: break
            try:
                data = await asyncio.wait_for(queue.get(), timeout=min(0.5, TIMEOUT_COMPARAISON - temps_ecoule))
                boutique = data.get("boutique")
                if boutique in buffer_par_site: buffer_par_site[boutique].extend(data.get("produits", []))
            except asyncio.TimeoutError: pass
            if all(w.done() for w in workers): break
    finally:
        for w in workers:
            if not w.done(): w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    meilleurs_matchs = []
    for boutique, produits in buffer_par_site.items():
        if produits:
            match = trouver_meilleur_match(query, produits)
            if match: meilleurs_matchs.append(match)

    async def return_empty(): return {"reference": "", "description": ""}
    taches_details = [fetch_missing_details(match) if not match.get("reference") or not match.get("description") else return_empty() for match in meilleurs_matchs]
    details = await asyncio.gather(*taches_details)

    for i, match in enumerate(meilleurs_matchs):
        if not match.get("reference") and details[i].get("reference"): match["reference"] = details[i]["reference"]
        if not match.get("description") and details[i].get("description"): match["description"] = details[i]["description"]

    details_map = {(m.get("boutique", ""), m.get("lien", "")): {"description": m.get("description", ""), "reference": m.get("reference", "")} for m in meilleurs_matchs}
    resultats_groupes = grouper_resultats_par_reference(meilleurs_matchs)
    resultats_a_cache = []

    for groupe in resultats_groupes:
        for offre in groupe["offres"]:
            cle = (offre.get("boutique", ""), offre.get("lien", ""))
            if cle in details_map: offre["description"] = details_map[cle]["description"]; offre["reference"] = details_map[cle]["reference"]
            else: offre.setdefault("description", ""); offre.setdefault("reference", "")
        resultat_envoye = {"nom_principal": groupe["nom_principal"], "reference": groupe["reference"], "est_meme_produit": groupe["est_meme_produit"], "offres": groupe["offres"]}
        resultats_a_cache.append(resultat_envoye); yield f"data: {json.dumps(resultat_envoye)}\n\n"

    if resultats_a_cache:
        resultat_cache.set("compare", query, resultats_a_cache)
        print(f"💾 Résultats comparaison mis en cache pour: {query} ({len(resultats_a_cache)} groupes)", flush=True)
    yield "data: [DONE]\n\n"

# ============================================================
#  LIFESPAN
# ============================================================
async def cache_cleanup_task():
    while True:
        await asyncio.sleep(300)
        nb = resultat_cache.cleanup_expired(CACHE_TTL)
        if nb > 0: print(f"🧹 Cache cleanup: {nb} entrées expirées supprimées", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Démarrage de l'API...", flush=True)
    
    print("⏳ Pré-chargement des clients HTTP...", flush=True)
    await get_http_client()
    await get_curl_client()
    print("✅ Clients HTTP prêts (httpx + curl_cffi) !", flush=True)
    
    cleanup_task = asyncio.create_task(cache_cleanup_task())
    yield 
    
    cleanup_task.cancel()
    try: await cleanup_task
    except asyncio.CancelledError: pass
    
    global _http_client, _curl_client
    if _http_client: await _http_client.aclose()
    if _curl_client:
        try: await _curl_client.close()
        except: pass
    resultat_cache.clear()
    print("🛑 Arrêt de l'API.", flush=True)

# ============================================================
#  FASTAPI APP & ROUTES
# ============================================================
app = FastAPI(title="API Comparateur", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def read_root():
    return {"status": "API is running", "docs": "/docs"}

@app.get("/api/search/stream")
async def rechercher_stream(q: str = Query(..., min_length=2)): return StreamingResponse(flux_de_recherche_ordonne(q), media_type="text/event-stream")

@app.get("/api/compare/stream")
async def comparer_stream(q: str = Query(..., min_length=2)): return StreamingResponse(flux_compare_stream(q), media_type="text/event-stream")

@app.get("/health")
async def health(): return {"status": "ok Scraping temps reel ", "boutiques": ["Tunisianet", "Spacenet", "Mytek"], "cache_size": resultat_cache.size()}

@app.get("/api/proxy-image")
async def proxy_image(img_url: str = Query(...)):
    if img_url in IMAGE_CACHE: return Response(content=IMAGE_CACHE[img_url][0], media_type=IMAGE_CACHE[img_url][1], headers={"Cache-Control": "public, max-age=86400"})
    client = await get_http_client()
    try:
        response = await client.get(img_url, follow_redirects=True, timeout=8.0)
        if len(IMAGE_CACHE) >= MAX_IMAGE_CACHE: IMAGE_CACHE.pop(next(iter(IMAGE_CACHE)))
        IMAGE_CACHE[img_url] = (response.content, response.headers.get("content-type", "image/jpeg"))
        return Response(content=response.content, media_type=response.headers.get("content-type", "image/jpeg"), headers={"Cache-Control": "public, max-age=86400"})
    except: return Response(status_code=404)

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)