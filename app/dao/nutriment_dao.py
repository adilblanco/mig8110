from app.db import get_connection
from app.config import (
    ENERGY_NUTRIMENT, FAT_NUTRIMENT, SATURATED_FAT_NUTRIMENT, 
    CARBS_NUTRIMENT, SUGARS_NUTRIMENT, PROTEINS_NUTRIMENT, SALT_NUTRIMENT,
    ALL_NUTRIENTS_COLUMNS
)

class NutrimentDAO:
    def list_nutriment_for_product(self, product_code: str, per: str = "serving") -> list[dict]:
        per_column = {
            "serving": "value_per_serving",
            "100g": "value_per_100g",
            "package": "value_per_package"
        }.get(per, "value_per_serving")

        sql = f"""
        SELECT
            nr.code AS code,
            nr.label AS label,
            pn.{per_column} AS value,
            nr.unit AS unit
        FROM product_nutriments pn
        JOIN nutriment_ref nr ON nr.code = pn.nutriment_code
        WHERE pn.product_code = ?
          AND pn.{per_column} IS NOT NULL
        ORDER BY nr.display_order NULLS LAST, nr.code
        """
        return execute_query(sql, [product_code])

        
    def get_nutrients_by_product_code(code: str):
        # On joint la liste des colonnes par des virgules
        columns = ", ".join(ALL_NUTRIENTS_COLUMNS)
        #query1 = f"SELECT {columns} FROM {TABLE_PRODUCTS} WHERE code = ?"
        query = """
        SELECT nutriments
        FROM main.canada_products
        WHERE code = ?
        """
        with get_connection() as conn:
            row = conn.execute(query, [code] ).fetchone()

        if not row:
            return None
        # 2. Mappage dynamique (Pythonic Way)
        # Zip associe chaque nom de colonne à sa valeur correspondante dans row
        # On nettoie les clés pour le frontend (ex: 'energy_100g' devient 'energy')
        
        #return {
        #    col.replace("_100g", "").replace("_NUTRIMENT", "").lower(): value 
        #    for col, value in zip(ALL_NUM_COLUMNS_CLEAN_KEYS, row)
        #}
        return {
            "energy": row[0],
            "fat": row[0],
            "saturated_fat": row[0],
            "carbohydrates": row[0],
            "sugars": row[0],
            "proteins": row[0],
            "salt": row[0]
        }
