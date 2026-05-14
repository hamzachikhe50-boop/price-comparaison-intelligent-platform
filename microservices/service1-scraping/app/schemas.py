from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class SiteEnum(str, Enum):
    MYTEK      = "mytek"
    SPACENET   = "spacenet"
    TUNISIANET = "tunisianet"
    ALL        = "all"


class TaskStatusEnum(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


class SortByEnum(str, Enum):
    PRIX_ASC  = "prix_asc"
    PRIX_DESC = "prix_desc"
    RECENT    = "recent"
    NOM       = "nom"


class ScrapeRequest(BaseModel):
    site: SiteEnum = Field(..., description="Site : mytek | spacenet | tunisianet | all")
    categories: Optional[List[str]] = Field(None)
    max_pages: int = Field(100, ge=1, le=500)

    model_config = {
        "json_schema_extra": {
            "example": {"site": "mytek", "categories": ["Smartphones"], "max_pages": 10}
        }
    }


class ScrapeTaskResponse(BaseModel):
    id:             int
    task_id:        str
    site:           str
    categories:     Optional[str]
    status:         TaskStatusEnum
    total_scraped:  int
    total_inserted: int
    total_updated:  int
    error_message:  Optional[str]
    started_at:     datetime
    finished_at:    Optional[datetime]

    model_config = {"from_attributes": True}


class ProductResponse(BaseModel):
    id:         int
    nom:        str
    prix:       Optional[str]
    prix_num:   Optional[float]
    image:      Optional[str]
    lien:       Optional[str]
    boutique:   str
    categorie:  str
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    pages:    int
    data:     List[ProductResponse]


class SearchResponse(BaseModel):
    query: str
    total: int
    data:  List[ProductResponse]


class StatsByBoutique(BaseModel):
    boutique:   str
    total:      int
    categories: int


class StatsByCategorie(BaseModel):
    categorie:  str
    boutique:   str
    total:      int
    prix_min:   Optional[float]
    prix_max:   Optional[float]
    prix_moyen: Optional[float]


class GlobalStats(BaseModel):
    total_products: int
    by_boutique:    List[StatsByBoutique]
    by_categorie:   List[StatsByCategorie]
    last_scrape:    Optional[datetime]


class CategoriesResponse(BaseModel):
    site:       str
    categories: List[str]
