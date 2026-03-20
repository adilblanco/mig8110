from typing import Optional, List
from pydantic import BaseModel
from .nutriment import Nutriment, PerLiteral

class Product(BaseModel):
    code: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    serving_size: Optional[str] = None

class ProductSummary(Product):
    pass

class ProductWithNutriments(BaseModel):
    product_code: str
    name: str
    serving_size: Optional[str] = None
    nutriments: List[Nutriment]

class Ingredient(BaseModel):
    ingredient: str

class ProductWithIngredients(BaseModel):
    product_code: str
    ingredients: List[Ingredient]