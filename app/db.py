import os
import duckdb
from dotenv import load_dotenv
from typing import Any, Dict, List

load_dotenv()

TOKEN_DUCKDB = os.getenv("TOKEN_DUCKDB")
DB_DUCKDB = os.getenv("DB_DUCKDB", "my_db")

def get_connection():
    """Retourne une nouvelle connexion DuckDB à chaque appel (thread-safe)."""
    if not TOKEN_DUCKDB or not DB_DUCKDB:
    raise RuntimeError("TOKEN_DUCKDB et/ou DB_DUCKDB manquants dans .env")
    return duckdb.connect(f"md:{DB_DUCKDB}?motherduck_token={TOKEN_DUCKDB}",read_only=True)

def execute_query(query: str, params: Dict[str, Any] | None = None) -> List[Dict]:
    """Exécute une requête SQL et retourne le résultat sous forme de liste de dictionnaires."""

    params = params or {}

    try:
        with get_connection() as conn:
            result = conn.execute(query, params)
            rows = result.fetchall()
            columns = [col[0] for col in result.description]
            return [dict(zip(columns, row)) for row in rows]

    except Exception as e:
        #   logger ici
        raise RuntimeError(f"Erreur lors de l'exécution SQL : {e}")



def get_connection1():
    conn = duckdb.connect(f"md:{DB_DUCKDB}",read_only=True)

    conn.execute("INSTALL motherduck")
    conn.execute("LOAD motherduck")

    conn.execute(f"SET motherduck_token='{TOKEN_DUCKDB}'")

    return conn