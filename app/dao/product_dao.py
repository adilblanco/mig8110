from typing import Optional
from app.db import get_connection

class ProductDAO:
    """
    Data Access Object pour les produits.
    Gère toutes les interactions SQL avec la base de données DuckDB.
    """

    @staticmethod
    def get_by_code_product(code: str) -> dict | None:
        """
        Exécute la requête SQL pour trouver un produit par son code.
        """
        # Utilisation de 'with' pour garantir la fermeture de la connexion
        query = """
        SELECT
            code,
            product_name,
            brands,
            categories,
            ingredients_text,
            nutriments 
        FROM main.canada_products
        WHERE code = ?
        """
        with get_connection() as conn:
            cursor = conn.execute(query, [code] )
            row = cursor.fetchone()

        if not row:
            return None

        # Retourne un dictionnaire pour faciliter le travail du Service
        return {
            "code": row[0],
            "name": row[1],
            "brand": row[2],
            "category": row[3],
            "ingredients": row[4],
            "nutriments": row[5],
            "energy_100g": row[5],
            "fat_100g": row[5],
            "sugars_100g": row[5],
            "proteins_100g": row[5]  
        }
    
    def search_by_name_product(self, name_product: str, limit: int = 20, offset: int = 0) -> list[dict]:
        query = """
        SELECT
            code,
            product_name,
            brands,
            categories
        FROM main.canada_products
        WHERE lower(product_name) LIKE lower(?)
        LIMIT ?
        """
        with get_connection() as conn:
            rows = conn.execute(query, [f"%{name_product}%", limit]).fetchall()

        if not rows:
            return None
        return [
            {
                "code": r[0],
                "name": r[1],
                "brand": r[2],
                "categories": r[3],
            }
            for r in rows
        ]

