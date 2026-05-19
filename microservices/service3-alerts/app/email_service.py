"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  email_service.py – Service 3 : Alertes
  Envoi d'emails via API Resend (Compatible Render)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
# Sur Resend, tu dois vérifier un nom de domaine. En attendant, 
# Resend permet d'utiliser cette adresse de test :
FROM_EMAIL = os.getenv("FROM_EMAIL", "PriceHunter <onboarding@resend.dev>")


def _envoyer_email(destinataire: str, sujet: str, html: str) -> bool:
    """
    Fonction interne pour envoyer un email via l'API Resend (HTTPS).
    Remplace smtplib qui est bloqué par Render.
    """
    if not RESEND_API_KEY:
        logger.warning("⚠️ RESEND_API_KEY non configurée dans .env. L'email ne partira pas.")
        return False

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": FROM_EMAIL,
                "to": [destinataire],
                "subject": sujet,
                "html": html
            },
            timeout=10
        )
        
        if response.status_code in (200, 202):
            logger.info(f"✅ Email envoyé à {destinataire}")
            return True
        else:
            logger.error(f"❌ Erreur API Resend ({response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Exception envoi email à {destinataire}: {e}")
        return False


def envoyer_alerte_prix(
    destinataire: str,
    product_name: str,
    product_url:  str,
    prix_cible:   float,
    prix_actuel:  float,
) -> bool:
    baisse = round(prix_cible - prix_actuel, 3)
    pct    = round((baisse / prix_cible) * 100, 1) if prix_cible else 0

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <div style="background:#1a1a2e;padding:24px;text-align:center;">
            <h1 style="color:#e8621a;margin:0;font-size:1.5rem;">PriceHunter</h1>
            <p style="color:#aaa;margin:8px 0 0;font-size:0.9rem;">Alerte de prix déclenchée</p>
        </div>
        <div style="padding:32px;">
            <h2 style="color:#333;margin:0 0 8px;">Votre prix cible est atteint !</h2>
            <p style="color:#666;margin:0 0 24px;">
                Le produit que vous surveillez est maintenant disponible à votre prix cible.
            </p>
            <div style="background:#f8f8f8;border-radius:6px;padding:20px;margin-bottom:24px;border-left:4px solid #e8621a;">
                <p style="margin:0 0 8px;font-size:0.85rem;color:#999;text-transform:uppercase;">Produit</p>
                <p style="margin:0 0 16px;font-weight:600;color:#333;">{product_name}</p>
                <div style="display:flex;gap:24px;flex-wrap:wrap;">
                    <div>
                        <p style="margin:0;font-size:0.8rem;color:#999;">Prix cible</p>
                        <p style="margin:4px 0 0;font-size:1.5rem;font-weight:700;color:#333;">{prix_cible:.3f} DT</p>
                    </div>
                    <div>
                        <p style="margin:0;font-size:0.8rem;color:#999;">Prix actuel</p>
                        <p style="margin:4px 0 0;font-size:1.5rem;font-weight:700;color:#22d17e;">{prix_actuel:.3f} DT</p>
                    </div>
                    <div>
                        <p style="margin:0;font-size:0.8rem;color:#999;">Économie</p>
                        <p style="margin:4px 0 0;font-size:1.5rem;font-weight:700;color:#e8621a;">-{pct}%</p>
                    </div>
                </div>
            </div>
            <a href="{product_url}"
               style="display:inline-block;background:#e8621a;color:white;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;">
                Voir le produit →
            </a>
            <p style="margin:24px 0 0;font-size:0.8rem;color:#aaa;">
                Cette alerte a été automatiquement désactivée après envoi.
            </p>
        </div>
    </div>
    </body></html>
    """

    sujet = f"Alerte prix : {product_name[:50]} → {prix_actuel:.3f} DT"
    return _envoyer_email(destinataire, sujet, html)


def envoyer_confirmation_alerte(
    destinataire: str,
    product_name: str,
    product_url:  str,
    prix_actuel:  float,
    prix_cible:   float,
    alerte_id:    int,
) -> bool:
    difference = round(prix_actuel - prix_cible, 3)
    pct        = round((difference / prix_actuel) * 100, 1) if prix_actuel else 0

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <div style="background:#1a1a2e;padding:24px;text-align:center;">
            <h1 style="color:#e8621a;margin:0;font-size:1.5rem;">PriceHunter</h1>
            <p style="color:#aaa;margin:8px 0 0;font-size:0.9rem;">Confirmation d'alerte</p>
        </div>
        <div style="padding:32px;">
            <div style="background:#e8f5e9;border-radius:8px;padding:16px;margin-bottom:24px;">
                <p style="margin:0;font-weight:700;color:#2e7d32;">Alerte activée avec succès !</p>
                <p style="margin:4px 0 0;font-size:0.85rem;color:#555;">Alerte #{alerte_id} — nous surveillons ce produit pour vous.</p>
            </div>
            <div style="background:#f8f8f8;border-radius:6px;padding:20px;margin-bottom:24px;border-left:4px solid #1a1a2e;">
                <p style="margin:0 0 8px;font-size:0.85rem;color:#999;text-transform:uppercase;">Produit surveillé</p>
                <p style="margin:0 0 20px;font-weight:600;color:#333;">{product_name}</p>
                <div style="display:flex;gap:24px;flex-wrap:wrap;">
                    <div>
                        <p style="margin:0;font-size:0.8rem;color:#999;">Prix actuel</p>
                        <p style="margin:4px 0 0;font-size:1.4rem;font-weight:700;color:#333;">{prix_actuel:.3f} DT</p>
                    </div>
                    <div>
                        <p style="margin:0;font-size:0.8rem;color:#999;">Votre prix cible</p>
                        <p style="margin:4px 0 0;font-size:1.4rem;font-weight:700;color:#e8621a;">{prix_cible:.3f} DT</p>
                    </div>
                    <div>
                        <p style="margin:0;font-size:0.8rem;color:#999;">Economie attendue</p>
                        <p style="margin:4px 0 0;font-size:1.4rem;font-weight:700;color:#1565c0;">-{pct}%</p>
                    </div>
                </div>
            </div>
            <p style="color:#555;margin:0 0 20px;">
                Vous recevrez un email dès que le prix descendra à
                <strong>{prix_cible:.3f} DT</strong> ou en dessous.
            </p>
            <a href="{product_url}"
               style="display:inline-block;background:#1a1a2e;color:white;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;">
                Voir le produit
            </a>
            <p style="margin:24px 0 0;font-size:0.8rem;color:#aaa;">
                L'alerte sera désactivée automatiquement après déclenchement.
            </p>
        </div>
    </div>
    </body></html>
    """

    sujet = f"Alerte activée : {product_name[:50]}"
    return _envoyer_email(destinataire, sujet, html)