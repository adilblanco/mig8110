# app/dao/product_dao.py
from typing import Optional
from app.db import execute_query
from app.utils.utilities import Utilities

class ProductDAO:
    """
    Data Access Object pour les produits.
    Gère toutes les interactions SQL avec la base de données DuckDB.
    """
    def get_products_list(product_name: Optional[str] = None, brand: Optional[str] = None, limit: int = 500) -> List[Dict]:
    """Liste des produits avec filtres, plafonnée à `limit` résultats."""
    query = f"""
        SELECT code, product_name, brands,
               energy_kcal_100g, fat_100g, salt_100g, sugars_100g,
               nutriscore_grade, ecoscore_grade, front_url
        FROM {TABLE_NAME}
        WHERE 1=1
    """
    params_query = []

    if product_name:
        query += " AND lower(product_name) LIKE ?"
        params_query.append(f"%{product_name.lower()}%")
    if brand:
        query += " AND lower(brands) LIKE ?"
        params_query.append(f"%{brand.lower()}%")

    query += " ORDER BY product_name NULLS LAST LIMIT ?"
    params_query.append(limit)

    return execute_query(query, params_query)

    def get_products_by_ingredients(ingredients_product: Optional[str] = None, limit: int = 500) -> List[Dict]:
    """Liste des produits à bases des ingrédients, plafonnée à `limit` résultats."""
    query = f"""
        SELECT 
            p.code_product,
            p.product_name,
            COUNT(DISTINCT i.id_ingredient) AS match_count
        FROM product p
        JOIN ProductIngredient pi ON p.code_product = pi.code_product
        JOIN ingredient i ON pi.id_ingredient = i.id_ingredient
        WHERE 1=1
    """
    params_query = []
    if ingredients_product :
        utilities = Utilities()
        ingredients_product = utilities.clean_string(ingredients_product)
        ingredients_product =ingredients_product.split(",")
        for ingredient_product in ingredients_product:
            query += " OR  LOWER(i.libelle) LIKE ?"
            params_query.append(f"%{ingredient_product.lower()}%")
        query += " GROUP BY p.code_product, p.product_name" 
        query += " ORDER BY match_count DESC, p.product_name NULLS LAST LIMIT ?" 
        params_query.append(limit)

    return execute_query(query, params_query)


    
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

