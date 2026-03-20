from config import db, execute_query

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