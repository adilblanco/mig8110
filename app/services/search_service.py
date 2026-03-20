from dao.product_dao import ProductDAO

class SearchService:
    def __init__(self):
        self.products = ProductDAO()

    def search_products(self, name: str, limit: int = 20, offset: int = 0):
        return self.products.search_by_name(name=name, limit=limit, offset=offset)