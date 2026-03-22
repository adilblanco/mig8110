from typing import Optional
from dao.product_dao import ProductDAO
from app.dao.product_dao import ProductDAO      # get_product_by_code
from app.dao.nutriment_dao import NutrimentDAO  #get_nutrients_by_product_code
from app.dao.ingredient_dao import IngredientDAO #get_ingredients_by_product_code


class ProductService:
    """
    Service gérant la logique métier pour les produits.
    Fait le pont entre le DAO (accès aux données) et l'API.
    """

    def __init__(self):
        self.product_dao = ProductDAO()
        self.nutriment_dao = NutrimentDAO()
        self.ingredient_dao = IngredientDAO()

    def search_by_name(self, name: str, limit: int = 20, offset: int = 0):
        return self.dao.search_by_name_product(name=name, limit=limit, offset=offset)

    @staticmethod
    def get_product_by_code(code: str) -> dict | None:
        """
        Récupère un produit simplifié par son code barre.
        """
        # Appel à la méthode de classe du DAO
        product = ProductDAO.get_by_code_product(code)

        if not product:
            return None

        # On retourne un dictionnaire formaté pour le frontend
        return {
            "code": product.get("code"),
            "name": product.get("product_name") or product.get("name"),
            "brand": product.get("brands") or product.get("brand")
        }

    @staticmethod
    def get_product_details(code: str):
        product =  self.product_dao.get_by_code_product(code)

        if not product:
            return None  

        nutrients =  self.nutriment_dao.get_nutrients_by_product_code(code)
        ingredients = self.ingredient_dao.get_ingredients_by_product_code(code)

        return {
            "product": product,
            "nutrients": nutrients,
            "ingredients": ingredients
        }

    def get_product_by_code1(code: str):
        product = dao_get_product(code)

        if not product:
            return None

        return {
            "code": product["code"],
            "name": product["name"],
            "brand": product["brand"]
        }

