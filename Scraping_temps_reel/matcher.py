# ============================================================
#  matcher.py  —  Comparaison Fuzzy + Référence (SKU)
#
#  Améliorations :
#  ✅ Garde la normalisation (ProMax, Unités, Couleurs)
#  ✅ Utilise l'algorithme 'difflib.SequenceMatcher'
#  ✅ NOUVEAU : Priorité absolue à la Référence (SKU)
#     - Si 2 produits ont la même référence, score = 1.0
#     - Nettoyage des crochets [ ] de Mytek/Tunisianet
#  ✅ Groupement des résultats par référence pour la comparaison
# ============================================================

import re
import difflib
from typing import Optional, List, Dict, Any

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
THRESHOLD = 0.75

SPLITS_TERMES = {
    "promax": "pro max", "ultramax": "ultra max", "ultrawide": "ultra wide",
    "superretina": "super retina", "macbookpro": "mac book pro", "macbookair": "mac book air",
    "macbook": "mac book", "airpodspro": "air pods pro", "airpods": "air pods",
    "imacpro": "imac pro", "ipadpro": "ipad pro", "ipadair": "ipad air",
    "ipadmini": "ipad mini", "watchultra": "watch ultra", "galaxytab": "galaxy tab",
    "galaxybook": "galaxy book", "galaxybuds": "galaxy buds", "xperia": "xperia",
    "snapdragon": "snapdragon", "dimensity": "dimensity",
}
ALIAS_UNITES = { "gb": "go", "tb": "to", "mb": "mo" }
BLACKLIST = {
    "noir","noire","onyx","obsidienne","charbon","carbon","graphite","gris","anthracite","ardoise",
    "argent","argente","aluminium","acier","titane","titanium","lunaire","silver",
    "blanc","blanche","ivoire","creme","lait","neige","starlight","moonlight","porcelaine",
    "naturel","transparent","clear","cristal","glace",
    "bleu","bleue","marine","cobalt","indigo","turquoise","cyan","azur","saphir","midnight",
    "rouge","bordeaux","carmin","grenat","rubis",
    "rose","fuchsia","magenta","corail","saumon",
    "vert","verte","emeraude","olive","foret","menthe","mint","kaki","sauge",
    "jaune","dore","doree","champagne","miel","ambre","canari",
    "orange","cuivre","bronze","rouille",
    "marron","brun","brune","chocolat","cafe","cacao","noisette","caramel",
    "beige","taupe","sable","camel","lin","ecru","nude",
    "violet","violette","lavande","lilas","mauve","prune","amethyste","pourpre","purple",
    "black","white","red","blue","green","yellow","pink","brown","gold","golden",
    "dark","light","matte","glossy",
    "edition","special","new","nouveau","nouvelle","serie","version","plus","reconditionne",
}

_CAMEL_RE = re.compile(r'([a-z])([A-Z])')
_DIGIT_ALPHA = re.compile(r'(\d)([a-zA-Z])')
_ALPHA_DIGIT = re.compile(r'([a-zA-Z])(\d)')
_UNITES_RE = re.compile(r'(\d+)\s*(go|gb|to|tb|mo|mb|mah|kwh|w|ghz|mhz|hz|mm|cm|pouces?|")', re.IGNORECASE)

# ══════════════════════════════════════════════════════════════════════════════
#  NORMALISATION
# ══════════════════════════════════════════════════════════════════════════════
def normaliser(texte: str) -> set[str]:
    s = texte
    for _ in range(5): s = _CAMEL_RE.sub(r'\1 \2', s)
    s = s.lower()
    s = _UNITES_RE.sub(lambda m: m.group(1) + " " + m.group(2).lower(), s)
    for _ in range(3):
        s = _DIGIT_ALPHA.sub(r'\1 \2', s)
        s = _ALPHA_DIGIT.sub(r'\1 \2', s)
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    for terme, remplacement in SPLITS_TERMES.items():
        s = re.sub(r'\b' + terme + r'\b', remplacement, s)
    
    tokens = s.split()
    tokens = [ALIAS_UNITES.get(t, t) for t in tokens]
    tokens = [t for t in tokens if t not in BLACKLIST and len(t) > 1]
    return set(tokens)

# ══════════════════════════════════════════════════════════════════════════════
#  NETTOYAGE RÉFÉRENCE (SKU)
# ══════════════════════════════════════════════════════════════════════════════
def nettoyer_reference(ref: str) -> str:
    """
    Nettoie une référence pour la comparaison.
    Exemples : 
      '[IPH-15-128-BLACK]' -> 'iph15128black'
      'MU7A3ZD/A'          -> 'mu7a3zda'
    """
    if not ref:
        return ""
    # Retirer les crochets [ ] utilisés par Mytek et Tunisianet
    ref_sans_crochets = re.sub(r'[\[\]]', '', ref)
    # Garder uniquement alphanumériques, mettre en minuscules
    return re.sub(r'[^a-z0-9]', '', ref_sans_crochets.lower())

# ══════════════════════════════════════════════════════════════════════════════
#  ALGORITHME FUZZY MATCHING + REF MATCHING
# ══════════════════════════════════════════════════════════════════════════════
def score_similarite(tokens_query: set, tokens_produit: set) -> float:
    if not tokens_query: return 0.0
    chiffres_query = {t for t in tokens_query if t.isdigit()}
    chiffres_produit = {t for t in tokens_produit if t.isdigit()}
    if chiffres_query and chiffres_produit:
        if chiffres_query != chiffres_produit: return 0.0
    str_query = " ".join(sorted(tokens_query))
    str_produit = " ".join(sorted(tokens_produit))
    return difflib.SequenceMatcher(None, str_query, str_produit).ratio()

def trouver_meilleur_match(query: str, produits: list) -> Optional[dict]:
    """Trouve le meilleur match en combinant Référence (priorité) et Fuzzy."""
    if not produits: return None
    tokens_query = normaliser(query)
    if not tokens_query: return None

    meilleur_score = 0.0
    meilleur_produit = None

    for produit in produits:
        score = 0.0
        
        # 1. Vérification par Référence (Score parfait si match)
        ref_produit = nettoyer_reference(produit.get("reference", ""))
        ref_query = nettoyer_reference(query) 
        
        if ref_produit and ref_query and ref_produit == ref_query:
            score = 1.0 # Match parfait garanti
        else:
            # 2. Sinon, fallback sur le Fuzzy Matching
            nom = produit.get("nom", "")
            if nom:
                tokens_produit = normaliser(nom)
                score = score_similarite(tokens_query, tokens_produit)
        
        if score > meilleur_score:
            meilleur_score = score
            meilleur_produit = produit

    if meilleur_score >= THRESHOLD:
        if meilleur_produit:
            meilleur_produit["score_match"] = round(meilleur_score, 2)
        return meilleur_produit
    
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  GROUPEMENT PAR RÉFÉRENCE (Pour la comparaison multi-sites)
# ══════════════════════════════════════════════════════════════════════════════
def grouper_resultats_par_reference(meilleurs_matchs: List[dict]) -> List[Dict[str, Any]]:
    """
    Regroupe les produits des différentes boutiques par référence.
    """
    groupes = {} 
    
    for produit in meilleurs_matchs:
        ref = nettoyer_reference(produit.get("reference", ""))
        cle_groupe = ref if ref else f"no_ref_{id(produit)}_{produit.get('boutique', '')}"
        
        if cle_groupe not in groupes:
            groupes[cle_groupe] = []
        groupes[cle_groupe].append(produit)
    
    resultats_formattes = []
    for cle, produits_groupe in groupes.items():
        def parse_prix(p):
            px = p.get("prix", "0")
            clean = re.sub(r'[^0-9.,]', '', px).replace(' ', '').replace(',', '.')
            try: return float(clean)
            except: return 999999.0
            
        produits_groupe.sort(key=parse_prix)
        meilleur_nom = max(produits_groupe, key=lambda p: p.get("score_match", 0)).get("nom", "Produit")
        
        resultats_formattes.append({
            "nom_principal": meilleur_nom,
            "reference": produits_groupe[0].get("reference", "Inconnue"),
            "description": produits_groupe[0].get("description", ""), # On récupère la description du 1er produit du groupe
            "est_meme_produit": len(produits_groupe) > 1 and bool(cle.startswith("no_ref_") is False),
            "offres": produits_groupe
        })
        
    resultats_formattes.sort(key=lambda g: (len(g["offres"]), g["offres"][0].get("score_match", 0)), reverse=True)
    
    return resultats_formattes