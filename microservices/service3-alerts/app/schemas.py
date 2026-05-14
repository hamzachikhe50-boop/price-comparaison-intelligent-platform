from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class AlertCreate(BaseModel):
    user_id:      str   = Field(..., description="Identifiant unique de l'utilisateur")
    user_email:   str   = Field(..., description="Email pour recevoir l'alerte")
    product_id:   int   = Field(..., description="ID du produit à surveiller")
    prix_cible:   float = Field(..., gt=0, description="Prix cible (déclenchement si prix_actuel ≤ prix_cible)")       
    prix_actuel:  Optional[float] = Field(None, description="Prix actuel du produit (optionnel, auto-rempli)")
    product_name: str   = Field("", description="Nom du produit (optionnel, auto-rempli)")
    product_url:  str   = Field("", description="URL du produit (optionnel, auto-rempli)")
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id":    "user_123",
                "user_email": "client@example.com",
                "product_id": 42,
                "prix_cible": 899.000,
                "prix_actuel": 799.000,
            }
        }
    }


class AlertResponse(BaseModel):
    id:           int
    user_id:      str
    user_email:   str
    product_id:   int
    product_name: Optional[str]
    product_url:  Optional[str]
    prix_cible:   float
    prix_actuel:  Optional[float]
    active:       bool
    created_at:   datetime
    triggered_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AlertVerifyReport(BaseModel):
    total_verifiees: int
    declenchees:     int
    emails_envoyes:  int
    erreurs:         int
    detail:          List[dict]


class AlertStats(BaseModel):
    total:       int
    actives:     int
    declenchees: int
    expirees:    int

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime

class FavoriteCreate(BaseModel):
    user_id:      str   = Field(..., description="Identifiant unique de l'utilisateur")
    product_id:   int   = Field(..., description="ID du produit")
    product_name: str   = Field("", description="Nom du produit")
    product_url:  str   = Field("", description="URL du produit")
    image_url:    str   = Field("", description="URL de l'image du produit")
    best_price:   Optional[float] = Field(None, description="Meilleur prix actuel")
    category:     str   = Field("", description="Catégorie du produit")
    
    # Ce validateur transforme les chaînes vides ou lettres en None (évite l'erreur 422)
    @validator('best_price', pre=True, always=True)
    def parse_best_price(cls, value):
        if value is None or value == "" or value == "N/A":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "user_123",
                "product_id": 42,
                "product_name": "iPhone 15 Pro Max",
                "best_price": 899.000,
            }
        }
    }

class FavoriteResponse(BaseModel):
    id:           int
    user_id:      str
    product_id:   int
    product_name: Optional[str]
    product_url:  Optional[str]
    image_url:    Optional[str]
    best_price:   Optional[float]
    category:     Optional[str]
    created_at:   datetime

    model_config = {"from_attributes": True}