import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

DUCKDB_TOKEN = os.getenv("DUCKDB_TOKEN")
DUCKDB_DB = os.getenv("DUCKDB_DB")
TABLE_NAME = "raw.products"

if not DUCKDB_TOKEN or not DUCKDB_DB:
    raise RuntimeError("DUCKDB_TOKEN et/ou DUCKDB_DB manquants dans .env")

conn_str = f"md:{DUCKDB_DB}?motherduck_token={DUCKDB_TOKEN}"
db = duckdb.connect(conn_str, read_only=True)

def execute_query(sql: str, params: List[Any] = None) -> List[Dict]:
    """Exécute une requête et retourne les résultats en dicts"""
    result = db.execute(sql, params or [])
    cols = [c[0] for c in result.description]
    rows = result.fetchall()
    return [dict(zip(cols, row)) for row in rows]