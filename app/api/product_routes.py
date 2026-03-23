# app/api/product_routes.py
from fastapi import APIRouter, HTTPException

from app.services.product_service import ProductService
#from app.services.nutriment_service import get_product_details

router = APIRouter(prefix="/products", tags=["Products"])

# 🔍 Recherche produit par code
@router.get("/{code}")
async def get_product(code: str):
    product = ProductService.get_product_by_code(code)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

# 🔍 Recherche produit par nom
@router.get("/{name}")
def search_product_by_name(name: str):
    products = search_by_name(name)

    if not products:
        raise HTTPException(status_code=404, detail="Product not found")

    return products

# 📊 Détails produit (nutriments + ingrédients)
@router.get("/{code}/details")
def get_product_details_route(code: str):
    details = get_product_details(code)

    if not details:
        raise HTTPException(status_code=404, detail="Product not found")

    return details
