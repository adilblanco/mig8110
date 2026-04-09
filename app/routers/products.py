# app/routers/products
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.dao.product_dao import ProductDAO

router = APIRouter(prefix="/products", tags=["products"])


#router = APIRouter(prefix="/products", tags=["products"])


@router.get("/")
def list_products(
    q: Optional[str] = Query(None, description="Recherche par nom de produit"),
    brand: Optional[str] = Query(None, description="Filtre par marque"),
    limit: int = Query(500, ge=1, le=1000, description="Nombre maximum de résultats"),
):
    # On initialise le DAO (ou on utilise la méthode static si définie)
    dao = ProductDAO()
    products = dao.search_by_name_product(name_product=q) if q else []
    
    if products is None:
        return []
    return products

@router.get("/{code}")
def get_product(code: str):
    # Appel de la méthode statique de ton DAO
    product = ProductDAO.get_by_code_product(code)
    
    if not product:
        raise HTTPException(status_code=404, detail="Produit non trouvé dans la base Canada")
    return product

