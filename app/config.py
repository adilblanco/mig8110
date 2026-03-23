import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

DUCKDB_TOKEN = os.getenv("TOKEN_DUCKDB")
DUCKDB_DB = os.getenv("DB_DUCKDB","my_db")

TABLE_NAME = "raw.products"

if not DUCKDB_TOKEN or not DUCKDB_DB:
    raise RuntimeError("DUCKDB_TOKEN et/ou DUCKDB_DB manquants dans .env")


DATABASE_PATH = f"md:{DUCKDB_DB}?motherduck_token={DUCKDB_TOKEN}"
#conn_str = f"md:{DUCKDB_DB}?motherduck_token={DUCKDB_TOKEN}"
#db = duckdb.connect(conn_str, read_only=True)

# Nutriments standards (Suffixe _NUTRIMENT pour la clarté)
ENERGY_NUTRIMENT = "energy_100g"
FAT_NUTRIMENT = "fat_100g"
SATURATED_FAT_NUTRIMENT = "saturated_fat_100g"
CARBS_NUTRIMENT = "carbohydrates_100g"
SUGARS_NUTRIMENT = "sugars_100g"
PROTEINS_NUTRIMENT = "proteins_100g"
SALT_NUTRIMENT = "salt_100g"
FIBER_NUTRIMENT = "fiber_100g"

# Liste groupée pour les requêtes SELECT automatiques
ALL_NUTRIENTS_COLUMNS = [
    ENERGY_NUTRIMENT,
    FAT_NUTRIMENT,
    SATURATED_FAT_NUTRIMENT,
    CARBS_NUTRIMENT,
    SUGARS_NUTRIMENT,
    PROTEINS_NUTRIMENT,
    SALT_NUTRIMENT,
    FIBER_NUTRIMENT
]