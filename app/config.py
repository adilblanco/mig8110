import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

TOKEN_DUCKDB = os.getenv("TOKEN_DUCKDB")
DB_DUCKDB = os.getenv("DB_DUCKDB","my_db")

TABLE_NAME = "raw.products"

if not TOKEN_DUCKDB or not DB_DUCKDB:
    raise RuntimeError("TOKEN_DUCKDB et/ou DB_DUCKDB manquants dans .env")


DATABASE_PATH = f"md:{DB_DUCKDB}?motherduck_token={TOKEN_DUCKDB}"
conn_str = f"md:{DB_DUCKDB}?motherduck_token={TOKEN_DUCKDB}"
db = duckdb.connect(conn_str, read_only=True)

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