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
            if isinstance(item, dict) and item.get("lang") == "main":
                return item.get("text")
    except TypeError:
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
            if isinstance(item, dict) and item.get("key") == image_key:
                rev = item.get("rev")
                if rev is not None:
                    return (
                        f"{BASE_IMAGE_URL}/"
                        f"{_build_code_path(code)}/"
                        f"{image_key}.{int(rev)}.400.jpg"
                    )
    except TypeError:
        return None

    return None


def _extract_nutriment(nutriments_list, nutriment_name):
    if nutriments_list is None:
        return None

    try:
        for item in nutriments_list:
            if isinstance(item, dict) and item.get("name") == nutriment_name:
                value = item.get("100g")
                if value is None:
                    return None
                return round(value, 2)
    except TypeError:
        return None

    return None


def _normalize_tag(tag):
    if not isinstance(tag, str):
        return None

    if ":" in tag:
        tag = tag.split(":", 1)[1]

    tag = tag.replace("-", " ")
    tag = tag.strip().lower()

    if not tag:
        return None

    return tag


def _normalize_ingredients_analysis(tags):
    if tags is None:
        return []

    if not isinstance(tags, (list, tuple)):
        return []

    normalized = []
    seen = set()

    for tag in tags:
        cleaned = _normalize_tag(tag)
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)

    return normalized


def _list_to_string(values):
    if isinstance(values, list) and len(values) > 0:
        return ", ".join(values)
    return None


def _safe_numeric(value):
    if pd.isna(value):
        return None
    return value


def handle(input_file_key, output_file_key):
    s3_bucket = os.environ["S3_BUCKET"]
    s3_endpoint = os.environ["S3_ENDPOINT"]
    s3_access_key = os.environ["S3_ACCESS_KEY"]
    s3_secret_key = os.environ["S3_SECRET_KEY"]

    logger.info(f"Transforming data from {input_file_key}...")

    s3_handler = S3FileHandler(
        s3_bucket,
        s3_endpoint,
        s3_access_key,
        s3_secret_key,
    )

    parquet_bytes = s3_handler.download_to_memory(input_file_key)
    df = pd.read_parquet(parquet_bytes)

    df["product_name"] = df["product_name"].apply(_extract_product_name)

    for image_key, col_name in IMAGE_KEYS:
        df[col_name] = [
            _extract_image_url(images, code, image_key)
            for images, code in zip(df["images"], df["code"])
        ]

    for nutriment_name, col_name in NUTRIMENTS:
        df[col_name] = df["nutriments"].apply(
            lambda lst, n=nutriment_name: _extract_nutriment(lst, n)
        )

    df["ingredients_analysis"] = df["ingredients_analysis_tags"].apply(
        _normalize_ingredients_analysis
    ).apply(_list_to_string)

    df["ingredients_percent_analysis"] = df["ingredients_percent_analysis"].apply(
        _safe_numeric
    )
    df["ingredients_from_palm_oil_n"] = df["ingredients_from_palm_oil_n"].apply(
        _safe_numeric
    )
    df["ingredients_n"] = df["ingredients_n"].apply(_safe_numeric)

    if not df.empty:
        logger.info(
            "Sample ingredients_analysis: %s",
            df["ingredients_analysis"].iloc[0],
        )
        logger.info(
            "Sample ingredients_percent_analysis: %s",
            df["ingredients_percent_analysis"].iloc[0],
        )
        logger.info(
            "Sample ingredients_from_palm_oil_n: %s",
            df["ingredients_from_palm_oil_n"].iloc[0],
        )
        logger.info(
            "Sample ingredients_n: %s",
            df["ingredients_n"].iloc[0],
        )

    df["nutriscore_grade"] = df["nutriscore_grade"].where(
        df["nutriscore_grade"].isin(["a", "b", "c", "d", "e"]),
        None,
    )
    df["ecoscore_grade"] = df["ecoscore_grade"].where(
        df["ecoscore_grade"].isin(["a-plus", "a", "b", "c", "d", "e", "f"]),
        None,
    )

    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[TARGET_COLUMNS]

    logger.info("Final columns: %s", df.columns.tolist())

    s3_handler.upload_dataframe(df, output_file_key)

    logger.info(f"Data uploaded to S3: {output_file_key} ({len(df)} records)")