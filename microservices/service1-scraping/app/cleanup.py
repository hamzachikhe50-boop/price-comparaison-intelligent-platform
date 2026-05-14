from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import PriceHistory

def cleanup_old_history(db: Session) -> int:
    """
    Supprime tous les enregistrements price_history
    de plus de 30 jours. Retourne le nombre de lignes supprimées.
    """
    limite = datetime.utcnow() - timedelta(days=30)

    nb = db.query(PriceHistory)\
           .filter(PriceHistory.scrape_date < limite)\
           .delete(synchronize_session=False)

    db.commit()
    print(f"🧹 Nettoyage historique : {nb} entrées supprimées (> 30 jours)")
    return nb