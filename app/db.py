import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

TOKEN_DUCKDB = os.getenv("TOKEN_DUCKDB")
DB_DUCKDB = os.getenv("DB_DUCKDB", "my_db")

def get_connection():
    return duckdb.connect(f"md:{DB_DUCKDB}?motherduck_token={TOKEN_DUCKDB}",read_only=True)

def execute_query(sql: str, params: List[Any] = None) -> List[Dict]:
    """Exécute une requête et retourne les résultats en dicts"""
    connexion = get_connection()
    result = connexion.execute(sql, params or [])
    cols = [c[0] for c in result.description]
    rows = result.fetchall()
    return [dict(zip(cols, row)) for row in rows]

def get_connection1():
    conn = duckdb.connect(f"md:{DB_DUCKDB}",,read_only=True)

    conn.execute("INSTALL motherduck")
    conn.execute("LOAD motherduck")

    conn.execute(f"SET motherduck_token='{TOKEN_DUCKDB}'")

    return conn