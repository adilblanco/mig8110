from typing import Optional
from db import query_to_dicts

class CategoryDAO:
    def get_by_id(self, category_id: str) -> Optional[dict]:
        sql = "SELECT id, name FROM categories WHERE id = ?"
        rows = query_to_dicts(sql, [category_id])
        return rows[0] if rows else None

    def list_all(self) -> list[dict]:
        return query_to_dicts("SELECT id, name FROM categories ORDER BY name")