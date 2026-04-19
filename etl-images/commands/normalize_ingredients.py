import os
import json
import logging
import re
import unicodedata
from typing import Any

import numpy as np
import pandas as pd
import requests

from common.s3 import S3FileHandler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Taxonomies OFF
# ---------------------------------------------------------------------------

INGREDIENTS_TXT_URL = (
    "https://raw.githubusercontent.com/openfoodfacts/"
    "openfoodfacts-server/main/taxonomies/food/ingredients.txt"
)

ADDITIVES_TXT_URL = (
    "https://raw.githubusercontent.com/openfoodfacts/"
    "openfoodfacts-server/main/taxonomies/additives.txt"
)

ADDITIVE_CLASSES_TXT_URL = (
    "https://raw.githubusercontent.com/openfoodfacts/"
    "openfoodfacts-server/main/taxonomies/additives_classes.txt"
)


# ---------------------------------------------------------------------------
# Helpers généraux
# ---------------------------------------------------------------------------

def _is_null(value: Any) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _clean_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    value = _strip_accents(value)
    value = value.replace("_", " ")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[\(\)\[\]\{\}\"'`]", " ", value)
    value = re.sub(r"[^a-zA-Z0-9%+\-/,:.\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _slugify(value: str) -> str:
    value = _clean_text(value).lower()
    value = value.replace("/", " ")
    value = value.replace(",", " ")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def _canonical_name_from_id(tag_id: str) -> str:
    """
    Extrait le nom depuis l'ingredient_id.
    en:coconut-cream → coconut-cream
    """
    return tag_id.split(":", 1)[1] if ":" in tag_id else tag_id


def _id_to_name(ingredient_id: str) -> str:
    """
    Convertit un ingredient_id en ingredient_name lisible.

    Exemples :
        en:coconut-cream  → coconut cream
        en:e150a          → e150a
        en:vitamin-b12    → vitamin b12
        fr:beurre-de-cacao → beurre de cacao
    """
    raw = _canonical_name_from_id(ingredient_id)
    return raw.replace("-", " ").replace("_", " ")


def _is_language_code(lang: str) -> bool:
    return lang.isalpha() and 2 <= len(lang) <= 3


def _safe_text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return cleaned if cleaned else None
    return None


def _normalize_alias_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _clean_text(value).lower()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _parse_ingredients_value(value: Any) -> list:
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
            logger.warning(f"Unable to parse ingredients JSON: {value[:120]}")
            return []
    return []


# ---------------------------------------------------------------------------
# Téléchargement taxonomies OFF
# ---------------------------------------------------------------------------

def _download_taxonomy(url: str) -> str:
    logger.info(f"Downloading taxonomy from {url}...")
    session = requests.Session()
    session.headers.update({"User-Agent": "FoodHealthAdvisor/1.0"})
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Parsing OFF générique
# ---------------------------------------------------------------------------

def _parse_taxonomy_with_properties(
    text: str,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """
    Parse une taxonomie OFF texte.

    Retourne :
    - canonical_map   : tag -> canonical_id
    - properties_map  : canonical_id -> dict de propriétés
    """
    canonical_map: dict[str, str] = {}
    properties_map: dict[str, dict[str, str]] = {}

    current_canonical: str | None = None

    def _flush():
        nonlocal current_canonical
        current_canonical = None

    def _to_tag(lang: str, value: str) -> str:
        slug = _slugify(value)
        return f"{lang}:{slug}" if slug else ""

    def _ensure_props(canonical_id: str):
        if canonical_id not in properties_map:
            properties_map[canonical_id] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            _flush()
            continue

        if line.startswith(("stopwords:", "synonyms:")):
            continue

        if line.startswith("< "):
            if current_canonical:
                parent = line[2:].strip().lower()
                if parent:
                    _ensure_props(current_canonical)
                    existing = properties_map[current_canonical].get("parents", "")
                    if existing:
                        properties_map[current_canonical]["parents"] = existing + "," + parent
                    else:
                        properties_map[current_canonical]["parents"] = parent
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
                canonical = _to_tag(key, values[0])
                if canonical:
                    current_canonical = canonical
                    canonical_map[canonical] = canonical
                    _ensure_props(canonical)

            if current_canonical:
                for val in values:
                    tag = _to_tag(key, val)
                    if tag:
                        canonical_map.setdefault(tag, current_canonical)
            continue

        if current_canonical is None:
            continue

        _ensure_props(current_canonical)
        properties_map[current_canonical][key] = rest

    logger.info(
        "Parsed taxonomy: %s canonical ids, %s known tags, %s property entries",
        sum(1 for k, v in canonical_map.items() if k == v),
        len(canonical_map),
        len(properties_map),
    )
    return canonical_map, properties_map


# ---------------------------------------------------------------------------
# Rôle OFF-only
# ---------------------------------------------------------------------------

def _split_off_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def _build_additive_role_map(
    additives_props: dict[str, dict[str, str]],
    additive_classes_canonical_map: dict[str, str],
) -> dict[str, str]:
    role_map: dict[str, str] = {}

    for additive_id, props in additives_props.items():
        raw_classes = props.get("additives_classes")
        if not raw_classes:
            continue

        class_tags = _split_off_values(raw_classes)
        if not class_tags:
            continue

        resolved_roles = []
        for class_tag in class_tags:
            canonical_class_id = additive_classes_canonical_map.get(class_tag, class_tag)
            role_name = _canonical_name_from_id(canonical_class_id)
            if role_name and role_name not in resolved_roles:
                resolved_roles.append(role_name)

        if resolved_roles:
            role_map[additive_id.lower()] = resolved_roles[0]

    logger.info("Built additive role map for %s additive ids", len(role_map))
    return role_map


def _infer_role_off_only(ingredient_id: str, additive_role_map: dict[str, str]) -> str | None:
    return additive_role_map.get((ingredient_id or "").lower())


# ---------------------------------------------------------------------------
# Normalisation ingrédient
# ---------------------------------------------------------------------------

def _candidate_tags_from_item(item: dict) -> list[str]:
    candidates = []

    raw_id = item.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        candidates.append(raw_id.strip().lower())

    raw_text = _safe_text(item.get("text"))
    if raw_text:
        slug = _slugify(raw_text)
        if slug:
            candidates.append(f"en:{slug}")
            candidates.append(f"fr:{slug}")

    unique = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _normalize_ingredient(
    item: dict,
    canonical_map: dict[str, str],
) -> dict | None:
    if not isinstance(item, dict):
        return None

    raw_text = _safe_text(item.get("text"))

    # 1. tentative via taxonomie OFF
    for candidate in _candidate_tags_from_item(item):
        if candidate in canonical_map:
            ingredient_id = canonical_map[candidate]
            return {
                "ingredient_id": ingredient_id,
                "raw_text": raw_text,
            }

    # 2. fallback sur l'id source
    raw_id = item.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        ingredient_id = raw_id.strip().lower()
        return {
            "ingredient_id": ingredient_id,
            "raw_text": raw_text,
        }

    # 3. fallback sur le texte source
    if raw_text:
        slug = _slugify(raw_text)
        if slug:
            ingredient_id = f"en:{slug}"
            return {
                "ingredient_id": ingredient_id,
                "raw_text": raw_text,
            }

    return None


# ---------------------------------------------------------------------------
# Flatten
# ---------------------------------------------------------------------------

def _flatten_tree(
    code: Any,
    ingredients: Any,
    ingredients_canonical_map: dict[str, str],
    additive_role_map: dict[str, str],
    all_product_rows: list[dict],
    all_component_rows: list[dict],
    all_alias_rows: list[dict],
    parent_ingredient_id: str | None = None,
) -> None:
    parsed = _parse_ingredients_value(ingredients)
    if not parsed:
        return

    for order, item in enumerate(parsed, start=1):
        normalized = _normalize_ingredient(item, ingredients_canonical_map)
        if not normalized:
            continue

        ingredient_id = normalized["ingredient_id"]
        ingredient_name = _id_to_name(ingredient_id)
        raw_text = normalized["raw_text"]

        if parent_ingredient_id is None:
            role = _infer_role_off_only(ingredient_id, additive_role_map)
            all_product_rows.append(
                {
                    "code": code,
                    "ingredient_id": ingredient_id,
                    "ingredient_order": order,
                    "role": role,
                }
            )
        else:
            all_component_rows.append(
                {
                    "ingredient_id": parent_ingredient_id,
                    "sous_ingredient_id": ingredient_id,
                    "sous_ingredient_name": ingredient_name,
                    "rang": order,
                }
            )

        # alias
        alias_name = _normalize_alias_text(raw_text)
        if alias_name and alias_name != ingredient_name:
            all_alias_rows.append(
                {
                    "ingredient_id": ingredient_id,
                    "alias_name": alias_name,
                }
            )

        children = item.get("ingredients")
        if children:
            _flatten_tree(
                code=code,
                ingredients=children,
                ingredients_canonical_map=ingredients_canonical_map,
                additive_role_map=additive_role_map,
                all_product_rows=all_product_rows,
                all_component_rows=all_component_rows,
                all_alias_rows=all_alias_rows,
                parent_ingredient_id=ingredient_id,
            )


# ---------------------------------------------------------------------------
# Construction tables finales
# ---------------------------------------------------------------------------

def _build_ingredients_table(
    product_rows: list[dict],
    component_rows: list[dict],
    alias_rows: list[dict],
) -> pd.DataFrame:
    ids = set()

    for row in product_rows:
        if row.get("ingredient_id"):
            ids.add(row["ingredient_id"])

    for row in component_rows:
        if row.get("ingredient_id"):
            ids.add(row["ingredient_id"])
        if row.get("sous_ingredient_id"):
            ids.add(row["sous_ingredient_id"])

    for row in alias_rows:
        if row.get("ingredient_id"):
            ids.add(row["ingredient_id"])

    records = [
        {
            "ingredient_id": ingredient_id,
            "ingredient_name": _id_to_name(ingredient_id),
        }
        for ingredient_id in sorted(ids)
    ]

    return pd.DataFrame(records, columns=["ingredient_id", "ingredient_name"])


def _empty_ingredients_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["ingredient_id", "ingredient_name"])


def _empty_product_ingredients_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "ingredient_id", "ingredient_order", "role"])


def _empty_sous_ingredients_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["ingredient_id", "sous_ingredient_id", "sous_ingredient_name", "rang"]
    )


def _empty_alias_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["ingredient_id", "alias_name"])


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def handle(
    input_file_key: str,
    ingredients_output_key: str,
    product_ingredients_output_key: str,
    sous_ingredients_output_key: str,
    ingredient_alias_output_key: str,
) -> None:
    s3_bucket = os.environ["S3_BUCKET"]
    s3_endpoint = os.environ["S3_ENDPOINT"]
    s3_access_key = os.environ["S3_ACCESS_KEY"]
    s3_secret_key = os.environ["S3_SECRET_KEY"]

    logger.info(f"Normalizing ingredients from {input_file_key}...")

    s3_handler = S3FileHandler(
        s3_bucket,
        s3_endpoint,
        s3_access_key,
        s3_secret_key,
    )

    raw = s3_handler.download_to_memory(input_file_key)
    df = pd.read_parquet(raw)

    if "ingredients" not in df.columns:
        logger.error(
            "COLUMN 'ingredients' NOT FOUND IN PARQUET. "
            f"Available columns: {df.columns.tolist()}"
        )
        s3_handler.upload_dataframe(_empty_ingredients_df(), ingredients_output_key)
        s3_handler.upload_dataframe(_empty_product_ingredients_df(), product_ingredients_output_key)
        s3_handler.upload_dataframe(_empty_sous_ingredients_df(), sous_ingredients_output_key)
        s3_handler.upload_dataframe(_empty_alias_df(), ingredient_alias_output_key)
        return

    sample = df["ingredients"].dropna().head(3)
    logger.info(
        f"[DIAG] ingredients — dtype={df['ingredients'].dtype} | "
        f"non-null={df['ingredients'].notna().sum()}/{len(df)} | "
        f"sample types={[type(v).__name__ for v in sample]} | "
        f"sample values={[repr(v)[:120] for v in sample]}"
    )

    # 1. Charger taxonomies OFF
    ingredients_txt = _download_taxonomy(INGREDIENTS_TXT_URL)
    additives_txt = _download_taxonomy(ADDITIVES_TXT_URL)
    additive_classes_txt = _download_taxonomy(ADDITIVE_CLASSES_TXT_URL)

    # 2. Parser taxonomies OFF
    ingredients_canonical_map, _ = _parse_taxonomy_with_properties(ingredients_txt)
    _, additives_props = _parse_taxonomy_with_properties(additives_txt)
    additive_classes_canonical_map, _ = _parse_taxonomy_with_properties(additive_classes_txt)

    # 3. Construire role map OFF-only
    additive_role_map = _build_additive_role_map(
        additives_props=additives_props,
        additive_classes_canonical_map=additive_classes_canonical_map,
    )

    # 4. Flatten
    all_product_rows: list[dict] = []
    all_component_rows: list[dict] = []
    all_alias_rows: list[dict] = []

    for _, row in df[["code", "ingredients"]].iterrows():
        _flatten_tree(
            code=row["code"],
            ingredients=row["ingredients"],
            ingredients_canonical_map=ingredients_canonical_map,
            additive_role_map=additive_role_map,
            all_product_rows=all_product_rows,
            all_component_rows=all_component_rows,
            all_alias_rows=all_alias_rows,
            parent_ingredient_id=None,
        )

    logger.info(f"Flattened product ingredient rows: {len(all_product_rows)}")
    logger.info(f"Flattened sous_ingredients rows: {len(all_component_rows)}")
    logger.info(f"Flattened alias rows: {len(all_alias_rows)}")

    # 5. product_ingredients
    df_product_ingredients = pd.DataFrame(
        all_product_rows,
        columns=["code", "ingredient_id", "ingredient_order", "role"],
    )
    if not df_product_ingredients.empty:
        df_product_ingredients = (
            df_product_ingredients
            .drop_duplicates()
            .sort_values(["code", "ingredient_order", "ingredient_id"])
            .reset_index(drop=True)
        )
    else:
        df_product_ingredients = _empty_product_ingredients_df()

    # 6. sous_ingredients
    df_sous_ingredients = pd.DataFrame(
        all_component_rows,
        columns=["ingredient_id", "sous_ingredient_id", "sous_ingredient_name", "rang"],
    )
    if not df_sous_ingredients.empty:
        df_sous_ingredients = (
            df_sous_ingredients
            .drop_duplicates()
            .sort_values(["ingredient_id", "rang", "sous_ingredient_id"])
            .reset_index(drop=True)
        )
    else:
        df_sous_ingredients = _empty_sous_ingredients_df()

    # 7. alias
    df_alias = pd.DataFrame(
        all_alias_rows,
        columns=["ingredient_id", "alias_name"],
    )
    if not df_alias.empty:
        df_alias = (
            df_alias
            .drop_duplicates()
            .sort_values(["ingredient_id", "alias_name"])
            .reset_index(drop=True)
        )
    else:
        df_alias = _empty_alias_df()

    # 8. ingredients (référentiel)
    df_ingredients = _build_ingredients_table(
        product_rows=all_product_rows,
        component_rows=all_component_rows,
        alias_rows=all_alias_rows,
    )
    if df_ingredients.empty:
        df_ingredients = _empty_ingredients_df()

    logger.info(f"df_ingredients shape: {df_ingredients.shape}")
    logger.info(f"df_product_ingredients shape: {df_product_ingredients.shape}")
    logger.info(f"df_sous_ingredients shape: {df_sous_ingredients.shape}")
    logger.info(f"df_alias shape: {df_alias.shape}")

    if not df_ingredients.empty:
        logger.info("df_ingredients head:\n" + df_ingredients.head(10).to_string())

    if not df_product_ingredients.empty:
        logger.info("df_product_ingredients head:\n" + df_product_ingredients.head(10).to_string())

    if not df_sous_ingredients.empty:
        logger.info("df_sous_ingredients head:\n" + df_sous_ingredients.head(10).to_string())

    if not df_alias.empty:
        logger.info("df_alias head:\n" + df_alias.head(10).to_string())

    # 9. Upload S3
    s3_handler.upload_dataframe(df_ingredients, ingredients_output_key)
    logger.info(f"ingredients uploaded -> {ingredients_output_key} ({len(df_ingredients)} records)")

    s3_handler.upload_dataframe(df_product_ingredients, product_ingredients_output_key)
    logger.info(
        f"product_ingredients uploaded -> {product_ingredients_output_key} "
        f"({len(df_product_ingredients)} records)"
    )

    s3_handler.upload_dataframe(df_sous_ingredients, sous_ingredients_output_key)
    logger.info(
        f"sous_ingredients uploaded -> {sous_ingredients_output_key} "
        f"({len(df_sous_ingredients)} records)"
    )

    s3_handler.upload_dataframe(df_alias, ingredient_alias_output_key)
    logger.info(
        f"ingredient_alias uploaded -> {ingredient_alias_output_key} "
        f"({len(df_alias)} records)"
    )