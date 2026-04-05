import os
import logging
import pandas as pd
from common.s3 import S3FileHandler
from config.target_columns import TARGET_COLUMNS

logger = logging.getLogger(__name__)

BASE_IMAGE_URL = "https://images.openfoodfacts.org/images/products"

NUTRIMENTS = [
    ("energy-kcal", "energy_kcal_100g"),
    ("fat", "fat_100g"),
    ("saturated-fat", "saturated_fat_100g"),
    ("trans-fat", "trans_fat_100g"),
    ("cholesterol", "cholesterol_100g"),
    ("sodium", "sodium_100g"),
    ("salt", "salt_100g"),
    ("carbohydrates", "carbohydrates_100g"),
    ("fiber", "fiber_100g"),
    ("sugars", "sugars_100g"),
    ("proteins", "proteins_100g"),
    ("calcium", "calcium_100g"),
    ("iron", "iron_100g"),
    ("potassium", "potassium_100g"),
]

IMAGE_KEYS = [
    ("front_en", "front_url"),
    ("ingredients_en", "ingredients_url"),
    ("nutrition_en", "nutrition_url"),
    ("packaging_en", "packaging_url"),
]


def _extract_product_name(product_name_list):
    if product_name_list is None:
        return None
    try:
        for item in product_name_list:
            if item["lang"] == "main":
                return item["text"]
    except (TypeError, KeyError):
        return None
    return None


def _build_code_path(code):
    code_padded = str(code).zfill(13)
    return f"{code_padded[:3]}/{code_padded[3:6]}/{code_padded[6:9]}/{code_padded[9:]}"


def _extract_image_url(images_list, code, image_key):
    if images_list is None:
        return None
    try:
        for item in images_list:
            if item["key"] == image_key:
                rev = item.get("rev")
                if rev is not None:
                    return f"{BASE_IMAGE_URL}/{_build_code_path(code)}/{image_key}.{int(rev)}.400.jpg"
    except (TypeError, KeyError, ValueError):
        return None
    return None


def _extract_nutriment(nutriments_list, nutriment_name):
    if nutriments_list is None:
        return None
    try:
        for item in nutriments_list:
            if item["name"] == nutriment_name:
                value = item.get("100g")
                return round(value, 2) if value is not None else None
    except (TypeError, KeyError):
        return None
    return None


def handle(input_file_key, output_file_key):
    s3_bucket = os.environ["S3_BUCKET"]
    s3_endpoint = os.environ["S3_ENDPOINT"]
    s3_access_key = os.environ["S3_ACCESS_KEY"]
    s3_secret_key = os.environ["S3_SECRET_KEY"]

    logger.info(f"Transforming data from {input_file_key}...")

    s3_handler = S3FileHandler(s3_bucket, s3_endpoint, s3_access_key, s3_secret_key)

    parquet_bytes = s3_handler.download_to_memory(input_file_key)
    df = pd.read_parquet(parquet_bytes)

    # product_name : extraction du libellé principal
    if "product_name" in df.columns:
        df["product_name"] = df["product_name"].apply(_extract_product_name)

    # images : reconstruction des URLs OFF
    if "images" in df.columns and "code" in df.columns:
        for image_key, col_name in IMAGE_KEYS:
            df[col_name] = [
                _extract_image_url(images, code, image_key)
                for images, code in zip(df["images"], df["code"])
            ]

    # nutriments : pivot vers colonnes plates
    if "nutriments" in df.columns:
        for nutriment_name, col_name in NUTRIMENTS:
            df[col_name] = df["nutriments"].apply(
                lambda lst, n=nutriment_name: _extract_nutriment(lst, n)
            )

    # whitelist grades
    if "nutriscore_grade" in df.columns:
        df["nutriscore_grade"] = df["nutriscore_grade"].where(
            df["nutriscore_grade"].isin(["a", "b", "c", "d", "e"]), None
        )

    if "ecoscore_grade" in df.columns:
        df["ecoscore_grade"] = df["ecoscore_grade"].where(
            df["ecoscore_grade"].isin(["a-plus", "a", "b", "c", "d", "e", "f"]), None
        )

    # IMPORTANT :
    # on garde la colonne ingredients pour normalize_ingredients
    # elle doit aussi être présente dans TARGET_COLUMNS
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            logger.warning(f"Column '{col}' not found in transformed data, filling with None.")
            df[col] = None

    df = df[TARGET_COLUMNS]

    s3_handler.upload_dataframe(df, output_file_key)
    logger.info(f"Data uploaded to S3: {output_file_key} ({len(df)} records)")