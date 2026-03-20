from fastapi import APIRouter, HTTPException, Query
from typing import List
from services.product_service import ProductService
from services.nutriment_service import NutrimentService
from services.search_service import SearchService
from schemas.product import ProductSummary, ProductWithNutriments
from schemas.nutriment import PerLiteral

router = APIRouter(prefix="/products", tags=["products"])

product_service = ProductService()
nutriment_service = NutrimentService()
search_service = SearchService()

@router.get("", response_model=List[ProductSummary])
def search_products(
    name: str = Query(..., min_length=1, description="Nom partiel du produit"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return search_service.search_products(name=name, limit=limit, offset=offset)

@router.get("/{product_id}", response_model=ProductSummary)
def get_product(product_id: str):
    product = product_service.get_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produit introuvable")
    return product

@router.get("/{product_id}/nutriments", response_model=ProductWithNutriments)
def get_product_nutriments(
    product_id: str,
    per: PerLiteral = Query("serving", description="serving | 100g | package"),
):
    result = nutriment_service.get_nutriments_for_product(product_id=product_id, per=per)
    if not result:
        raise HTTPException(status_code=404, detail="Nutriments indisponibles pour ce produit")
    return result