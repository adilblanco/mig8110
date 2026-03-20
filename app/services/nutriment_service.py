from dao.nutriment_dao import NutrimentDAO
from dao.product_dao import ProductDAO
from schemas.product import ProductWithNutriments
from schemas.nutriment import Nutriment

class NutrimentService:
    def __init__(self):
        self.nutriments = NutrimentDAO()
        self.products = ProductDAO()

    def get_nutriments_for_product(self, product_id: str, per: str = "serving") -> dict | None:
        product = self.products.get_product_by_code(product_id)
        if not product:
            return None

        rows = self.nutriments.list_nutriment_for_product(product_id=product_id, per=per)
        nutriments = [
            Nutriment(
                code=r["code"],
                label=r["label"],
                value=float(r["value"]),
                unit=r["unit"],
                per=per
            ) for r in rows
        ]

        return ProductWithNutriments(
            product_id=product["id"],
            name=product["name"],
            serving_size=product.get("serving_size"),
            nutriments=nutriments
        ).model_dump()