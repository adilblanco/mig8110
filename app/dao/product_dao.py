from typing import Optional
from config import db, execute_query

class ProductDAO:
    def get_product_by_code(self, product_code: str) -> Optional[dict]:
        sql = """
        SELECT p.code, p.name, p.brand, c.name AS category, p.serving_size
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.id = ?
        """
        rows = execute_query(sql, [product_code])
        return rows[0] if rows else None

    def search_product_by_name(self, name: str, limit: int = 20, offset: int = 0) -> list[dict]:
        sql = """
        SELECT p.code, p.name, p.brand, c.name AS category, p.serving_size
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE lower(p.name) LIKE '%' || lower(?) || '%'
        ORDER BY p.name
        LIMIT ? OFFSET ?
        """
        return query_to_dicts(sql, [name, limit, offset])