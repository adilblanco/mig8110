from app.db import get_connection

class IngredientDAO:
    def get_ingredients_by_product_code(code: str):

        query = """
        SELECT 
            ingredients_text
        FROM main.canada_products
        WHERE code = ?
        """
        with get_connection() as conn:
            row = conn.execute(query, [code] ).fetchone()

        if not row or not row[0]:
            return []

        # les ingrédients sont souvent une string séparée
        ingredients = row[0].split(",")

        return [i.strip() for i in ingredients]