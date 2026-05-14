"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  email_service.py – Service 3 : Alertes
  Envoi d'emails via Gmail SMTP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_USER     = os.getenv("GMAIL_USER", "")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


def envoyer_alerte_prix(
    destinataire: str,
    product_name: str,
    product_url:  str,
    prix_cible:   float,
    prix_actuel:  float,
) -> bool:
    """
    Envoie un email HTML d'alerte de prix via Gmail SMTP.
    Retourne True si succès, False sinon.
    """
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("❌ GMAIL_USER ou GMAIL_APP_PASSWORD non configuré dans .env")
        return False

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

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Alerte prix : {product_name[:50]} → {prix_actuel:.3f} DT"
        msg["From"]    = GMAIL_USER
        msg["To"]      = destinataire
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, destinataire, msg.as_string())

        print(f"✅ Email envoyé à {destinataire} pour '{product_name}'")
        return True

    except Exception as e:
        print(f"❌ Erreur envoi email à {destinataire}: {e}")
        return False


def envoyer_confirmation_alerte(
    destinataire: str,
    product_name: str,
    product_url:  str,
    prix_actuel:  float,
    prix_cible:   float,
    alerte_id:    int,
) -> bool:
    """
    Envoie un email de confirmation quand une alerte est creee.
    """
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("GMAIL_USER ou GMAIL_APP_PASSWORD non configure dans .env")
        return False

    difference = round(prix_actuel - prix_cible, 3)
    pct        = round((difference / prix_actuel) * 100, 1) if prix_actuel else 0

    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">
        <div style="background:#1a1a2e;padding:24px;text-align:center;">
            <h1 style="color:#e8621a;margin:0;font-size:1.5rem;">PriceHunter</h1>
            <p style="color:#aaa;margin:8px 0 0;font-size:0.9rem;">Confirmation d alerte</p>
        </div>
        <div style="padding:32px;">
            <div style="background:#e8f5e9;border-radius:8px;padding:16px;margin-bottom:24px;">
                <p style="margin:0;font-weight:700;color:#2e7d32;">Alerte activee avec succes !</p>
                <p style="margin:4px 0 0;font-size:0.85rem;color:#555;">Alerte #{alerte_id} — nous surveillons ce produit pour vous.</p>
            </div>
            <div style="background:#f8f8f8;border-radius:6px;padding:20px;margin-bottom:24px;border-left:4px solid #1a1a2e;">
                <p style="margin:0 0 8px;font-size:0.85rem;color:#999;text-transform:uppercase;">Produit surveille</p>
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
                Vous recevrez un email des que le prix descend a
                <strong>{prix_cible:.3f} DT</strong> ou en dessous.
            </p>
            <a href="{product_url}"
               style="display:inline-block;background:#1a1a2e;color:white;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;">
                Voir le produit
            </a>
            <p style="margin:24px 0 0;font-size:0.8rem;color:#aaa;">
                L alerte sera desactivee automatiquement apres declenchement.
            </p>
        </div>
    </div>
    </body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Alerte activee : {product_name[:50]}"
        msg["From"]    = GMAIL_USER
        msg["To"]      = destinataire
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, destinataire, msg.as_string())

        print(f"Confirmation envoyee a {destinataire} pour alerte #{alerte_id}")
        return True

    except Exception as e:
        print(f"Erreur envoi confirmation a {destinataire}: {e}")
        return False
