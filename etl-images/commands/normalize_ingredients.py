import os
import json
import logging
import requests
import pandas as pd
import numpy as np
from common.s3 import S3FileHandler

logger = logging.getLogger(__name__)

INGREDIENTS_TXT_URL = (
    "https://raw.githubusercontent.com/openfoodfacts/"
    "openfoodfacts-server/main/taxonomies/food/ingredients.txt"
)


# ---------------------------------------------------------------------------
# 1. Téléchargement du fichier de référence OFF
# ---------------------------------------------------------------------------

def _download_ingredients_txt(url: str) -> str:
    logger.info(f"Downloading ingredients taxonomy from {url}...")
    session = requests.Session()
    session.headers.update({"User-Agent": "FoodHealthAdvisor/1.0"})
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# 2. Helpers généraux
# ---------------------------------------------------------------------------

def _is_null(value) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))


def _slugify(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def _is_language_code(lang: str) -> bool:
    return lang.isalpha() and 2 <= len(lang) <= 3


def _parse_ingredients_value(value):
    """
    Convertit la colonne ingredients en liste Python.
    Gère :
      - liste déjà parsée
      - string JSON
      - null
    """
    if _is_null(value):
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            logger.warning(f"Impossible de parser ingredients: {value[:120]}")
            return []

    return []


# ---------------------------------------------------------------------------
# 3. Parsing enrichi de la taxonomie OFF
# ---------------------------------------------------------------------------

def _parse_taxonomy(text: str) -> tuple[dict, dict]:
    canonical_map: dict[str, str] = {}
    ingredient_props: dict[str, dict] = {}

    current_canonical: str | None = None

    def _flush():
        nonlocal current_canonical
        current_canonical = None

    def _to_tag(lang: str, value: str) -> str:
        return f"{lang}:{_slugify(value)}"

    def _canonical_name_from_id(ingredient_id: str) -> str:
        return ingredient_id.split(":", 1)[1] if ":" in ingredient_id else ingredient_id

    def _ensure_props(ingredient_id: str):
        if ingredient_id not in ingredient_props:
            ingredient_props[ingredient_id] = {
                "ingredient_id": ingredient_id,
                "ingredient_name": _canonical_name_from_id(ingredient_id),
                "is_in_taxonomy": True,
                "vegan": None,
                "vegetarian": None,
                "from_palm_oil": None,
            }

    def _normalize_property_value(value: str):
        val = value.strip().lower()
        if val in {"yes", "true"}:
            return True
        if val in {"no", "false"}:
            return False
        if val in {"maybe", "unknown", "sometimes", ""}:
            return None
        return None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            _flush()
            continue

        if line.startswith(("stopwords:", "synonyms:", "< ")):
            continue

        if ":" not in line:
            continue

        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.strip()

        if _is_language_code(key):
            values = [v.strip() for v in rest.split(",") if v.strip()]
            if not values:
                continue

            if current_canonical is None and key == "en":
                current_canonical = _to_tag(key, values[0])
                canonical_map[current_canonical] = current_canonical
                _ensure_props(current_canonical)

            if current_canonical:
                for val in values:
                    canonical_map.setdefault(_to_tag(key, val), current_canonical)

            continue

        if current_canonical is None:
            continue

        _ensure_props(current_canonical)

        if key == "vegan":
            ingredient_props[current_canonical]["vegan"] = _normalize_property_value(rest)
        elif key == "vegetarian":
            ingredient_props[current_canonical]["vegetarian"] = _normalize_property_value(rest)
        elif key == "from_palm_oil":
            ingredient_props[current_canonical]["from_palm_oil"] = _normalize_property_value(rest)

    _flush()

    logger.info(
        f"Taxonomy parsed: "
        f"{sum(1 for k, v in canonical_map.items() if k == v)} canonical ingredients, "
        f"{len(canonical_map)} known tags, "
        f"{len(ingredient_props)} ingredients with properties"
    )

    return canonical_map, ingredient_props


# ---------------------------------------------------------------------------
# 4. Matching d’un ingrédient OFF
# ---------------------------------------------------------------------------

def _candidate_tags_from_ingredient(item: dict) -> list[str]:
    candidates = []

    ingredient_id = item.get("id")
    if isinstance(ingredient_id, str) and ingredient_id.strip():
        candidates.append(ingredient_id.strip().lower())

    text = item.get("text")
    if isinstance(text, str) and text.strip():
        slug = _slugify(text)
        candidates.extend([
            f"en:{slug}",
            f"fr:{slug}",
        ])

    return candidates


def _canonical_name_from_id(ingredient_id: str) -> str:
    return ingredient_id.split(":", 1)[1] if ":" in ingredient_id else ingredient_id


def _normalize_ingredient(item: dict, canonical_map: dict, ingredient_props: dict) -> dict | None:
    if not isinstance(item, dict):
        return None

    ingredient_text = item.get("text")
    ingredient_text = ingredient_text.strip() if isinstance(ingredient_text, str) and ingredient_text.strip() else None

    for candidate in _candidate_tags_from_ingredient(item):
        if candidate in canonical_map:
            ingredient_id = canonical_map[candidate]
            props = ingredient_props.get(
                ingredient_id,
                {
                    "ingredient_id": ingredient_id,
                    "ingredient_name": _canonical_name_from_id(ingredient_id),
                    "is_in_taxonomy": True,
                    "vegan": None,
                    "vegetarian": None,
                    "from_palm_oil": None,
                },
            )
            return {
                "ingredient_id": ingredient_id,
                "ingredient_name": props["ingredient_name"],
                "ingredient_text": ingredient_text,
                "is_in_taxonomy": True,
                "vegan": props.get("vegan"),
                "vegetarian": props.get("vegetarian"),
                "from_palm_oil": props.get("from_palm_oil"),
            }

    raw_id = item.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        ingredient_id = raw_id.strip().lower()
    elif ingredient_text:
        ingredient_id = f"en:{_slugify(ingredient_text)}"
    else:
        return None

    return {
        "ingredient_id": ingredient_id,
        "ingredient_name": _canonical_name_from_id(ingredient_id),
        "ingredient_text": ingredient_text,
        "is_in_taxonomy": False,
        "vegan": None,
        "vegetarian": None,
        "from_palm_oil": None,
    }


# ---------------------------------------------------------------------------
# 5. Flatten récursif
# ---------------------------------------------------------------------------

def _flatten_ingredients_tree(
    code,
    ingredients,
    canonical_map: dict,
    ingredient_props: dict,
    level: int = 0,
    parent_ingredient_id: str | None = None,
) -> list[dict]:
    rows = []

    ingredients = _parse_ingredients_value(ingredients)

    if not ingredients:
        return rows

    for order, item in enumerate(ingredients, start=1):
        if not isinstance(item, dict):
            continue

        normalized = _normalize_ingredient(item, canonical_map, ingredient_props)
        if not normalized:
            continue

        row = {
            "code": code,
            "ingredient_id": normalized["ingredient_id"],
            "ingredient_text": normalized["ingredient_text"],
            "ingredient_order": order,
            "ingredient_level": level,
            "parent_ingredient_id": parent_ingredient_id,
            "ingredient_name": normalized["ingredient_name"],
            "is_in_taxonomy": normalized["is_in_taxonomy"],
            "vegan": normalized["vegan"],
            "vegetarian": normalized["vegetarian"],
            "from_palm_oil": normalized["from_palm_oil"],
        }
        rows.append(row)

        children = item.get("ingredients")
        if children:
            rows.extend(
                _flatten_ingredients_tree(
                    code=code,
                    ingredients=children,
                    canonical_map=canonical_map,
                    ingredient_props=ingredient_props,
                    level=level + 1,
                    parent_ingredient_id=normalized["ingredient_id"],
                )
            )

    return rows


# ---------------------------------------------------------------------------
# 6. Construction de la table ingredients
# ---------------------------------------------------------------------------

def _build_ingredients_table(df_product_ingredients: pd.DataFrame) -> pd.DataFrame:
    if df_product_ingredients.empty:
        return pd.DataFrame(
            columns=[
                "ingredient_id",
                "ingredient_name",
                "is_in_taxonomy",
                "vegan",
                "vegetarian",
                "from_palm_oil",
            ]
        )

    return (
        df_product_ingredients[
            [
                "ingredient_id",
                "ingredient_name",
                "is_in_taxonomy",
                "vegan",
                "vegetarian",
                "from_palm_oil",
            ]
        ]
        .drop_duplicates(subset=["ingredient_id"])
        .sort_values("ingredient_id")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 7. Point d’entrée principal
# ---------------------------------------------------------------------------

def handle(
    input_file_key: str,
    ingredients_output_key: str,
    product_ingredients_output_key: str,
) -> None:
    s3_bucket = os.environ["S3_BUCKET"]
    s3_endpoint = os.environ["S3_ENDPOINT"]
    s3_access_key = os.environ["S3_ACCESS_KEY"]
    s3_secret_key = os.environ["S3_SECRET_KEY"]

    logger.info(f"Normalizing ingredients from {input_file_key}...")

    s3_handler = S3FileHandler(s3_bucket, s3_endpoint, s3_access_key, s3_secret_key)

    raw = s3_handler.download_to_memory(input_file_key)
    df = pd.read_parquet(raw)

    if "ingredients" not in df.columns:
        logger.error(
            "COLUMN 'ingredients' NOT FOUND IN PARQUET. "
            f"Available columns: {df.columns.tolist()}"
        )
        s3_handler.upload_dataframe(
            pd.DataFrame(
                columns=[
                    "ingredient_id",
                    "ingredient_name",
                    "is_in_taxonomy",
                    "vegan",
                    "vegetarian",
                    "from_palm_oil",
                ]
            ),
            ingredients_output_key,
        )
        s3_handler.upload_dataframe(
            pd.DataFrame(
                columns=[
                    "code",
                    "ingredient_id",
                    "ingredient_text",
                    "ingredient_order",
                    "ingredient_level",
                    "parent_ingredient_id",
                ]
            ),
            product_ingredients_output_key,
        )
        return

    col = df["ingredients"]
    sample = col.dropna().head(3)
    logger.info(
        f"[DIAG] ingredients — dtype={col.dtype} | "
        f"non-null={col.notna().sum()}/{len(df)} | "
        f"sample types={[type(v).__name__ for v in sample]} | "
        f"sample values={[repr(v)[:120] for v in sample]}"
    )

    ingredients_txt = _download_ingredients_txt(INGREDIENTS_TXT_URL)
    canonical_map, ingredient_props = _parse_taxonomy(ingredients_txt)

    all_rows = []
    for _, row in df[["code", "ingredients"]].iterrows():
        all_rows.extend(
            _flatten_ingredients_tree(
                code=row["code"],
                ingredients=row["ingredients"],
                canonical_map=canonical_map,
                ingredient_props=ingredient_props,
                level=0,
                parent_ingredient_id=None,
            )
        )

    logger.info(f"Flattened ingredient rows: {len(all_rows)}")

    df_full = pd.DataFrame(
        all_rows,
        columns=[
            "code",
            "ingredient_id",
            "ingredient_text",
            "ingredient_order",
            "ingredient_level",
            "parent_ingredient_id",
            "ingredient_name",
            "is_in_taxonomy",
            "vegan",
            "vegetarian",
            "from_palm_oil",
        ],
    )

    if not df_full.empty:
        df_full = df_full.drop_duplicates().reset_index(drop=True)

    df_ingredients = _build_ingredients_table(df_full)

    df_product_ingredients = df_full[
        [
            "code",
            "ingredient_id",
            "ingredient_text",
            "ingredient_order",
            "ingredient_level",
            "parent_ingredient_id",
        ]
    ].copy()

    s3_handler.upload_dataframe(df_ingredients, ingredients_output_key)
    logger.info(
        f"ingredients uploaded → {ingredients_output_key} ({len(df_ingredients)} records)"
    )

    s3_handler.upload_dataframe(df_product_ingredients, product_ingredients_output_key)
    logger.info(
        f"product_ingredients uploaded → {product_ingredients_output_key} ({len(df_product_ingredients)} records)"
    )