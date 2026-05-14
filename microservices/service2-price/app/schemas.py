from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TimelinePoint(BaseModel):
    jour:            str
    prix_num:        float
    prix_txt:        Optional[str]
    scrape_effectue: bool
    prix_change:     bool


class PriceHistoryItem(BaseModel):
    id:               int
    product_id:       int
    ancien_prix:      Optional[float]
    nouveau_prix:     Optional[float]
    ancien_prix_txt:  Optional[str]
    nouveau_prix_txt: Optional[str]
    scrape_date:      str

    class Config:
        from_attributes = True


class PriceHistoryResponse(BaseModel):
    product_id:    int
    nom:           str
    boutique:      str
    prix_actuel:   Optional[str]
    total_changes: int
    timeline:      List[TimelinePoint]
    historique:    List[PriceHistoryItem]


class PriceStatsResponse(BaseModel):
    product_id:     int
    nom:            str
    boutique:       str
    prix_actuel:    Optional[float]
    prix_min:       Optional[float]
    prix_max:       Optional[float]
    prix_moyen:     Optional[float]
    nb_jours_suivi: int
    nb_changements: int
    variation_pct:  Optional[float]


class PriceChangeItem(BaseModel):
    id:               int
    product_id:       int
    nom:              str
    boutique:         str
    lien:             Optional[str]
    ancien_prix:      Optional[float]
    nouveau_prix:     Optional[float]
    ancien_prix_txt:  Optional[str]
    nouveau_prix_txt: Optional[str]
    scrape_date:      str


class PredictionResponse(BaseModel):
    product_id:      int
    current_price:   float
    predicted_price: float
    days_ahead:      int
    prediction_date: str
    trend:           str   # "up" | "down" | "stable"
