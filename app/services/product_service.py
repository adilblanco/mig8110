from typing import Optional
from dao.product_dao import ProductDAO

class ProductService:
    def __init__(self):
        self.dao = ProductDAO()

    def get_by_id(self, product_id: str) -> Optional[dict]:
        return self.dao.get_by_id(product_id)

    def search_by_name(self, name: str, limit: int = 20, offset: int = 0):
        return self.dao.search_by_name(name=name, limit=limit, offset=offset)