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


def _normalize_free_text(value):
    if not isinstance(value, str):
        return None

    value = value.strip().lower()

    if not value:
        return None

    return value


def _normalize_ingredient_tag(tag):
    cleaned = _normalize_tag(tag)

    if not cleaned:
        return None

    if cleaned in GENERIC_INGREDIENTS:
        return None

    return cleaned


def _to_iterable(value):
    if value is None:
        return []

    if isinstance(value, str):
        return []

    if isinstance(value, (list, tuple)):
        return value

    if hasattr(value, "__iter__"):
        try:
            return list(value)
        except TypeError:
            return []

    return []


def _normalize_ingredients(tags):
    """
    Normalisation de ingredients_original_tags.
    """
    values = _to_iterable(tags)

    normalized = []
    seen = set()

    for tag in values:
        cleaned = _normalize_ingredient_tag(tag)
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)

    return normalized


def _normalize_ingredient_object_name(item):
    """
    Pour la colonne `ingredients`, on garde tous les ingrédients.
    Priorité à `text`, fallback sur `id`.
    """
    if not isinstance(item, dict):
        return None

    raw_value = item.get("text")
    if not raw_value:
        raw_value = item.get("id")

    if not isinstance(raw_value, str):
        return None

    if raw_value == item.get("id"):
        cleaned = _normalize_tag(raw_value)
    else:
        cleaned = _normalize_free_text(raw_value)

    return cleaned


def _format_optional_percent(value):
    if value is None:
        return None

    try:
        return str(round(float(value), 2))
    except (TypeError, ValueError):
        return None


def _normalize_flag(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "unknown"

    if isinstance(value, str):
        value = value.strip().lower()
        if value:
            return value

    return "unknown"


def _format_ingredient_object(item):
    """
    Construit une représentation complète d'un ingrédient
    en gardant les éléments importants dans une seule chaîne.
    """
    if not isinstance(item, dict):
        return None

    name = _normalize_ingredient_object_name(item)
    if not name:
        return None

    parts = []

    percent = _format_optional_percent(item.get("percent"))
    if percent is not None:
        parts.append(f"percent={percent}%")

    percent_estimate = _format_optional_percent(item.get("percent_estimate"))
    if percent_estimate is not None:
        parts.append(f"percent_estimate={percent_estimate}%")

    percent_min = _format_optional_percent(item.get("percent_min"))
    if percent_min is not None:
        parts.append(f"percent_min={percent_min}%")

    percent_max = _format_optional_percent(item.get("percent_max"))
    if percent_max is not None:
        parts.append(f"percent_max={percent_max}%")

    parts.append(f"vegan={_normalize_flag(item.get('vegan'))}")
    parts.append(f"vegetarian={_normalize_flag(item.get('vegetarian'))}")
    parts.append(f"from_palm_oil={_normalize_flag(item.get('from_palm_oil'))}")

    processing = _normalize_tag(item.get("processing"))
    if processing:
        parts.append(f"processing={processing}")

    labels = _normalize_tag(item.get("labels"))
    if labels:
        parts.append(f"labels={labels}")

    origins = _normalize_free_text(item.get("origins"))
    if origins:
        parts.append(f"origins={origins}")

    return f"{name} [{' ; '.join(parts)}]"


def _collect_nested_ingredient_details(items, normalized, seen):
    """
    Parcours récursif de la colonne `ingredients`
    en gardant tous les éléments et les sous-ingrédients.
    """
    for item in _to_iterable(items):
        if not isinstance(item, dict):
            continue

        cleaned = _format_ingredient_object(item)
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)

        nested_items = item.get("ingredients")
        if nested_items:
            _collect_nested_ingredient_details(nested_items, normalized, seen)


def _normalize_ingredients_struct(ingredients):
    """
    Normalise la colonne `ingredients` en gardant :
    - nom
    - pourcentages
    - vegan
    - vegetarian
    - from_palm_oil
    - processing
    - labels
    - sous-ingrédients
    """
    normalized = []
    seen = set()

    _collect_nested_ingredient_details(ingredients, normalized, seen)

    return normalized


def _normalize_analysis_tags(tags):
    """
    Normalisation de ingredients_analysis_tags.
    """
    values = _to_iterable(tags)

    normalized = []
    seen = set()

    for tag in values:
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

    # product_name
    df["product_name"] = df["product_name"].apply(_extract_product_name)

    # image URLs
    for image_key, col_name in IMAGE_KEYS:
        df[col_name] = [
            _extract_image_url(images, code, image_key)
            for images, code in zip(df["images"], df["code"])
        ]

    # nutriments
    for nutriment_name, col_name in NUTRIMENTS:
        df[col_name] = df["nutriments"].apply(
            lambda lst, n=nutriment_name: _extract_nutriment(lst, n)
        )

    # ingredients_original_tags -> colonne simple et lisible
    df["ingredients_normalized"] = df["ingredients_original_tags"].apply(
        _normalize_ingredients
    ).apply(_list_to_string)

    # ingredients -> colonne riche dans la même colonne
    df["ingredients_struct_normalized"] = df["ingredients"].apply(
        _normalize_ingredients_struct
    ).apply(_list_to_string)

    # ingredients_analysis_tags
    df["ingredients_analysis_normalized"] = df["ingredients_analysis_tags"].apply(
        _normalize_analysis_tags
    ).apply(_list_to_string)

    # colonnes numériques liées aux ingrédients
    df["ingredients_percent_analysis"] = df["ingredients_percent_analysis"].apply(
        _safe_numeric
    )
    df["ingredients_from_palm_oil_n"] = df["ingredients_from_palm_oil_n"].apply(
        _safe_numeric
    )
    df["ingredients_n"] = df["ingredients_n"].apply(_safe_numeric)

    # Debug
    if not df.empty:
        logger.info(
            "Sample ingredients_normalized: %s",
            df["ingredients_normalized"].iloc[0],
        )
        logger.info(
            "Sample ingredients_struct_normalized: %s",
            df["ingredients_struct_normalized"].iloc[0],
        )
        logger.info(
            "Sample ingredients_analysis_normalized: %s",
            df["ingredients_analysis_normalized"].iloc[0],
        )

    # nutriscore / ecoscore
    df["nutriscore_grade"] = df["nutriscore_grade"].where(
        df["nutriscore_grade"].isin(["a", "b", "c", "d", "e"]),
        None,
    )
    df["ecoscore_grade"] = df["ecoscore_grade"].where(
        df["ecoscore_grade"].isin(["a-plus", "a", "b", "c", "d", "e", "f"]),
        None,
    )

    # Projection finale
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[TARGET_COLUMNS]

    logger.info("Final columns: %s", df.columns.tolist())

    s3_handler.upload_dataframe(df, output_file_key)

    logger.info(f"Data uploaded to S3: {output_file_key} ({len(df)} records)")