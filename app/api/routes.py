from fastapi import APIRouter
from .product_routes import router as product_router

api_router = APIRouter()
api_router.include_router(product_router)