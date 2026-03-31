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

GENERIC_INGREDIENTS = {
    "added sugar",
    "disaccharide",
    "monosaccharide",
    "polysaccharide",
    "carbohydrate",
    "sweetener",
    "dairy",
    "milk product",
    "plant",
    "fruit",
    "ferment",
    "enzyme",
    "compound ingredient",
    "preparation",
}


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


def _normalize_ingredient_tag(tag):
    if not isinstance(tag, str):
        return None

    if ":" in tag:
        tag = tag.split(":", 1)[1]

    tag = tag.replace("-", " ")
    tag = tag.strip().lower()

    if not tag:
        return None

    if tag in GENERIC_INGREDIENTS:
        return None

    return tag


def _normalize_ingredients(tags):
    """
    Normalise ingredients_original_tags même si la valeur n'est pas
    une list Python stricte (ex: numpy.ndarray, array-like, etc.).
    """
    if tags is None:
        return []

    if isinstance(tags, str):
        return []

    if isinstance(tags, (list, tuple)):
        values = tags
    elif hasattr(tags, "__iter__"):
        try:
            values = list(tags)
        except TypeError:
            return []
    else:
        return []

    normalized = []
    seen = set()

    for tag in values:
        cleaned = _normalize_ingredient_tag(tag)
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)

    return normalized


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

    # product_name: Open Food Facts stocke le nom du produit comme une liste
    # d'objets [{lang, text}, ...]. On extrait uniquement le texte associé à
    # lang="main", qui représente le nom canonique du produit.
    df["product_name"] = df["product_name"].apply(_extract_product_name)

    # image URLs: reconstruction des URLs à partir du code produit et de la révision.
    for image_key, col_name in IMAGE_KEYS:
        df[col_name] = [
            _extract_image_url(images, code, image_key)
            for images, code in zip(df["images"], df["code"])
        ]

    # nutriments: pivot des valeurs nutritionnelles en colonnes plates.
    for nutriment_name, col_name in NUTRIMENTS:
        df[col_name] = df["nutriments"].apply(
            lambda lst, n=nutriment_name: _extract_nutriment(lst, n)
        )

    # ingredients_normalized: normalisation de ingredients_original_tags
    # - retrait du préfixe langue (ex: en:)
    # - remplacement des tirets par des espaces
    # - passage en minuscule
    # - suppression des termes trop génériques
    # - déduplication
    df["ingredients_normalized"] = df["ingredients_original_tags"].apply(
        _normalize_ingredients
    )

    # Logs de debug utiles pour vérifier le vrai format des ingrédients
    if not df.empty:
        logger.info(
            "Sample ingredients_original_tags type: %s",
            type(df["ingredients_original_tags"].iloc[0]),
        )
        logger.info(
            "Sample ingredients_original_tags value: %s",
            df["ingredients_original_tags"].iloc[0],
        )
        logger.info(
            "Sample ingredients_normalized value: %s",
            df["ingredients_normalized"].iloc[0],
        )

    # nutriscore_grade / ecoscore_grade: normalisation des valeurs hors whitelist.
    df["nutriscore_grade"] = df["nutriscore_grade"].where(
        df["nutriscore_grade"].isin(["a", "b", "c", "d", "e"]),
        None,
    )
    df["ecoscore_grade"] = df["ecoscore_grade"].where(
        df["ecoscore_grade"].isin(["a-plus", "a", "b", "c", "d", "e", "f"]),
        None,
    )

    # Projection finale sur TARGET_COLUMNS.
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[TARGET_COLUMNS]

    logger.info("Final columns before upload: %s", df.columns.tolist())

    s3_handler.upload_dataframe(df, output_file_key)

    logger.info(f"Data uploaded to S3: {output_file_key} ({len(df)} records)")