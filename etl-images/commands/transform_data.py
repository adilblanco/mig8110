import os
import re
import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from common.s3 import S3FileHandler

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

PRODUCT_COLUMNS = [
    "code",
    "product_name",
    "brands",
    "quantity",
    "serving_size",
    "ecoscore_score",
    "ecoscore_grade",
    "nutriscore_score",
    "nutriscore_grade",
    "front_url",
    "ingredients_url",
    "nutrition_url",
    "packaging_url",
    "energy_kcal_100g",
    "fat_100g",
    "saturated_fat_100g",
    "trans_fat_100g",
    "cholesterol_100g",
    "sodium_100g",
    "salt_100g",
    "carbohydrates_100g",
    "fiber_100g",
    "sugars_100g",
    "proteins_100g",
    "calcium_100g",
    "iron_100g",
    "potassium_100g",
]

INGREDIENT_COLUMNS = [
    "ingredient_id",
    "ingredient_text",
    "ingredient_name",
]

PRODUCT_INGREDIENT_COLUMNS = [
    "code",
    "ingredient_id",
    "ingredient_order",
    "ingredient_level",
    "parent_ingredient_id",
    "percent",
    "percent_min",
    "percent_max",
    "percent_estimate",
]

STOPWORDS_EN = [
    "contains less than 2% of the following",
    "contains one or more of the following",
    "may contain one or more of the following",
    "less than 1% of",
    "manufactured in a facility that also processes",
    "manufactiured in a facility that also processes",
    "added to enhance freshness",
    "added to maintain flavor and freshness",
    "in varying proportions",
    "produced with",
    "for freshness",
    "with added",
    "contains",
    "contain",
    "including",
    "minimum",
    "based",
    "edible",
    "substances",
    "with",
    "from",
    "and",
    "or",
]

SYNONYM_REPLACEMENTS = {
    "colourings": "colorings",
    "colouring": "coloring",
    "coloured": "colored",
    "colourful": "colorful",
    "colour": "color",
    "fibre": "fiber",
    "hydrolysed": "hydrolyzed",
    "pasteurised": "pasteurized",
    "flavour": "flavor",
    "flavouring": "flavoring",
    "soya": "soy",
}

CANONICAL_MAPPING = {
    "soybean": "soy",
    "soy bean": "soy",
    "soybean paste": "soy paste",
    "soybean flour": "soy flour",
    "soybean lecithin": "soy lecithin",
    "gmo free soy lecithin": "soy lecithin",
    "non gmo soy lecithin": "soy lecithin",
    "emulsifer soy lecithin": "soy lecithin",
    "lecithin sunflower": "sunflower lecithin",
    "non gmo sunflower lecithin": "sunflower lecithin",
    "natural paprika extract": "paprika extract",
    "paprika oleoresin": "paprika extract",
    "capsanthin": "paprika extract",
    "capsicum extract": "paprika extract",
    "carotin": "carotene",
    "mixed carotenes": "carotene",
    "cartenoids": "carotenoids",
    "tetraterpenoids": "carotenoids",
    "caramel sugar syrup": "caramelised sugar syrup",
    "palmolein": "palm oil",
    "palm fruit": "palm",
    "canola oil": "canola",
    "olive oil": "olive oil",
    "cane sugar": "sugar",
    "beet sugar": "sugar",
    "sea salt": "salt",
    "dried onion": "dehydrated onion",
    "artificial flavors": "artificial flavoring",
    "natural flavors": "natural flavoring",
    "caramel color": "caramel coloring",
}

NOISE_PATTERNS = [
    r"^contains less than \d+",
    r"^may contain",
    r"^manufactured in a facility",
    r"^manufactiured in a facility",
    r"^trans fat \d",
    r"^tells ou ho in a serving",
    r"^and milk$",
    r"^dv$",
    r"^veg$",
]

NOISE_IDS = {
    "en:contains-less-than-2-of",
    "en:manufactiured-in-a-facility-that-also-processes-egg",
    "en:and-milk",
    "en:dv",
}


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _extract_product_name(product_name_list: Any) -> Optional[str]:
    if product_name_list is None:
        return None

    try:
        for item in product_name_list:
            if isinstance(item, dict) and item.get("lang") == "main":
                return item.get("text")
    except TypeError:
        return None

    return None


def _build_code_path(code: Any) -> str:
    code_padded = str(code).zfill(13)
    return f"{code_padded[:3]}/{code_padded[3:6]}/{code_padded[6:9]}/{code_padded[9:]}"


def _extract_image_url(images_list: Any, code: Any, image_key: str) -> Optional[str]:
    images = _as_list(images_list)
    if not images:
        return None

    for item in images:
        if isinstance(item, dict) and item.get("key") == image_key:
            rev = item.get("rev")
            if rev is not None:
                return (
                    f"{BASE_IMAGE_URL}/"
                    f"{_build_code_path(code)}/"
                    f"{image_key}.{int(rev)}.400.jpg"
                )

    return None


def _extract_nutriment(nutriments_list: Any, nutriment_name: str) -> Optional[float]:
    nutriments = _as_list(nutriments_list)
    if not nutriments:
        return None

    for item in nutriments:
        if isinstance(item, dict) and item.get("name") == nutriment_name:
            value = item.get("100g")
            if value is None:
                return None
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                return None

    return None


def _safe_numeric(value: Any) -> Optional[float]:
    if pd.isna(value):
        return None
    return value


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:
        pass

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return []

    return []


def _parse_percent(node: Dict[str, Any], key: str) -> Optional[float]:
    value = node.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_raw_ingredient_text(text: str) -> str:
    text = _strip_accents(text)
    text = text.replace("_", " ")
    text = text.replace('"', " ")
    text = text.replace("“", " ").replace("”", " ")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("/", " ")
    text = text.replace("-", " ")
    text = re.sub(r"[^a-zA-Z0-9 %]+", " ", text)
    return _normalize_spaces(text)


def _normalize_ingredient_name(
    ingredient_text: Optional[str],
    ingredient_id: Optional[str],
) -> Optional[str]:
    raw = None

    if isinstance(ingredient_text, str) and ingredient_text.strip():
        raw = ingredient_text.strip()
    elif ingredient_id:
        raw = re.sub(r"^[a-z]{2}:", "", str(ingredient_id).strip())

    if not raw:
        return None

    value = _clean_raw_ingredient_text(raw).lower()

    for stopword in sorted(STOPWORDS_EN, key=len, reverse=True):
        pattern = r"\b" + re.escape(stopword) + r"\b"
        value = re.sub(pattern, " ", value)

    value = _normalize_spaces(value)

    for src, dst in SYNONYM_REPLACEMENTS.items():
        pattern = r"\b" + re.escape(src) + r"\b"
        value = re.sub(pattern, dst, value)

    value = _normalize_spaces(value)

    if value in CANONICAL_MAPPING:
        value = CANONICAL_MAPPING[value]

    value = _normalize_spaces(value)

    return value or None


def _is_probable_noise(ingredient_id: Optional[str], ingredient_name: Optional[str]) -> bool:
    if ingredient_id in NOISE_IDS:
        return True

    if not ingredient_name:
        return True

    if len(ingredient_name) > 120:
        return True

    for pattern in NOISE_PATTERNS:
        if re.search(pattern, ingredient_name):
            return True

    return False


def _extract_ingredient_nodes(
    product_code: Any,
    ingredients: Any,
    level: int = 0,
    parent_ingredient_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for idx, node in enumerate(_as_list(ingredients), start=1):
        if not isinstance(node, dict):
            continue

        ingredient_id = node.get("id")
        ingredient_text = node.get("text")

        if ingredient_id is None:
            continue

        normalized_name = _normalize_ingredient_name(ingredient_text, ingredient_id)

        rows.append(
            {
                "code": str(product_code) if product_code is not None else None,
                "ingredient_id": ingredient_id,
                "ingredient_text": ingredient_text,
                "ingredient_name": normalized_name,
                "ingredient_order": idx,
                "ingredient_level": level,
                "parent_ingredient_id": parent_ingredient_id,
                "percent": _parse_percent(node, "percent"),
                "percent_min": _parse_percent(node, "percent_min"),
                "percent_max": _parse_percent(node, "percent_max"),
                "percent_estimate": _parse_percent(node, "percent_estimate"),
            }
        )

        child_rows = _extract_ingredient_nodes(
            product_code=product_code,
            ingredients=node.get("ingredients"),
            level=level + 1,
            parent_ingredient_id=ingredient_id,
        )
        rows.extend(child_rows)

    return rows


def _prepare_products(df: pd.DataFrame) -> pd.DataFrame:
    products_df = df.copy()

    products_df["code"] = products_df["code"].astype(str)
    products_df["product_name"] = products_df["product_name"].apply(_extract_product_name)

    for image_key, col_name in IMAGE_KEYS:
        products_df[col_name] = [
            _extract_image_url(images, code, image_key)
            for images, code in zip(products_df["images"], products_df["code"])
        ]

    for nutriment_name, col_name in NUTRIMENTS:
        products_df[col_name] = products_df["nutriments"].apply(
            lambda lst, n=nutriment_name: _extract_nutriment(lst, n)
        )

    products_df["ecoscore_score"] = products_df["ecoscore_score"].apply(_safe_numeric)
    products_df["nutriscore_score"] = products_df["nutriscore_score"].apply(_safe_numeric)

    products_df["nutriscore_grade"] = products_df["nutriscore_grade"].where(
        products_df["nutriscore_grade"].isin(["a", "b", "c", "d", "e"]),
        None,
    )

    products_df["ecoscore_grade"] = products_df["ecoscore_grade"].where(
        products_df["ecoscore_grade"].isin(["a-plus", "a", "b", "c", "d", "e", "f"]),
        None,
    )

    for col in PRODUCT_COLUMNS:
        if col not in products_df.columns:
            products_df[col] = None

    products_df = products_df[PRODUCT_COLUMNS].drop_duplicates(subset=["code"])
    return products_df


def _prepare_ingredients_and_links(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    ingredient_rows: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        ingredients_value = row.get("ingredients")
        parsed_ingredients = _as_list(ingredients_value)

        if idx < 5:
            logger.info(
                "Row %s - code=%s - ingredients raw type=%s - parsed_len=%s",
                idx,
                row.get("code"),
                type(ingredients_value).__name__,
                len(parsed_ingredients),
            )

        ingredient_rows.extend(_extract_ingredient_nodes(row["code"], ingredients_value))

    logger.info("Total extracted ingredient rows before DataFrame: %s", len(ingredient_rows))

    links_df = pd.DataFrame(ingredient_rows)

    if links_df.empty:
        logger.warning("No ingredient rows extracted. ingredients_df and product_ingredients_df will be empty.")
        ingredients_df = pd.DataFrame(columns=INGREDIENT_COLUMNS)
        product_ingredients_df = pd.DataFrame(columns=PRODUCT_INGREDIENT_COLUMNS)
        return ingredients_df, product_ingredients_df

    links_df["ingredient_name"] = links_df.apply(
        lambda r: _normalize_ingredient_name(r.get("ingredient_text"), r.get("ingredient_id")),
        axis=1,
    )

    links_df["is_noise"] = links_df.apply(
        lambda r: _is_probable_noise(r.get("ingredient_id"), r.get("ingredient_name")),
        axis=1,
    )

    links_df = links_df[links_df["ingredient_id"].notna()].copy()
    links_df = links_df[links_df["ingredient_name"].notna()].copy()
    links_df = links_df[~links_df["is_noise"]].copy()

    ingredients_df = (
        links_df[["ingredient_id", "ingredient_text", "ingredient_name"]]
        .sort_values(["ingredient_id", "ingredient_name"])
        .drop_duplicates(subset=["ingredient_id"], keep="first")
        .reset_index(drop=True)
    )

    product_ingredients_df = (
        links_df[PRODUCT_INGREDIENT_COLUMNS]
        .drop_duplicates(subset=["code", "ingredient_id", "ingredient_order", "ingredient_level"])
        .reset_index(drop=True)
    )

    return ingredients_df, product_ingredients_df


def handle(
    input_file_key: str,
    products_output_file_key: str,
    ingredients_output_file_key: str,
    product_ingredients_output_file_key: str,
):
    s3_bucket = os.environ["S3_BUCKET"]
    s3_endpoint = os.environ["S3_ENDPOINT"]
    s3_access_key = os.environ["S3_ACCESS_KEY"]
    s3_secret_key = os.environ["S3_SECRET_KEY"]

    logger.info("Transforming data from %s", input_file_key)

    s3_handler = S3FileHandler(
        s3_bucket,
        s3_endpoint,
        s3_access_key,
        s3_secret_key,
    )

    parquet_bytes = s3_handler.download_to_memory(input_file_key)
    df = pd.read_parquet(parquet_bytes)

    logger.info("Input rows: %s", len(df))
    if "ingredients" in df.columns and not df.empty:
        logger.info("Sample ingredients type: %s", type(df['ingredients'].iloc[0]).__name__)

    products_df = _prepare_products(df)
    ingredients_df, product_ingredients_df = _prepare_ingredients_and_links(df)

    logger.info("Products rows: %s", len(products_df))
    logger.info("Ingredients rows: %s", len(ingredients_df))
    logger.info("Product_ingredients rows: %s", len(product_ingredients_df))

    s3_handler.upload_dataframe(products_df, products_output_file_key)
    s3_handler.upload_dataframe(ingredients_df, ingredients_output_file_key)
    s3_handler.upload_dataframe(product_ingredients_df, product_ingredients_output_file_key)

    logger.info("Uploaded products to %s", products_output_file_key)
    logger.info("Uploaded ingredients to %s", ingredients_output_file_key)
    logger.info("Uploaded product_ingredients to %s", product_ingredients_output_file_key)