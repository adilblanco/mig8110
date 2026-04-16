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
    return tag_id.split(":", 1)[1] if ":" in tag_id else tag_id


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
# Standardisation du nom d'ingrédient
# ---------------------------------------------------------------------------

# Mots/termes à préserver tels quels (insensibles à la casse)
_PRESERVE_CASE = {
    "ph": "pH",
    "dha": "DHA",
    "epa": "EPA",
    "bha": "BHA",
    "bht": "BHT",
    "msg": "MSG",
    "hfcs": "HFCS",
    "gmo": "GMO",
    "tbhq": "TBHQ",
    "dl": "DL",
}

# Petits mots qui restent en minuscule sauf en début de nom
_LOWERCASE_WORDS = {
    "de", "du", "des", "le", "la", "les", "et", "ou", "au", "aux", "en",
    "of", "the", "and", "or", "in", "with", "from", "for", "a", "an",
}


def _smart_title_case(text: str) -> str:
    """
    Title case intelligent pour les noms d'ingrédients.

    Exemples :
        water              → Water
        COCOA MASS         → Cocoa Mass
        caramel color      → Caramel Color
        e150a              → E150a
        vitamin b12        → Vitamin B12
        ph adjuster        → pH Adjuster
        beurre de cacao    → Beurre de Cacao
        DL-Methionine      → DL-Methionine
        soy lecithin       → Soy Lecithin
    """
    if not text:
        return text

    words = text.split()
    result = []

    for i, word in enumerate(words):
        lower = word.lower()

        # 1. Acronymes et termes à préserver
        if lower in _PRESERVE_CASE:
            result.append(_PRESERVE_CASE[lower])
            continue

        # 2. Codes additifs : e150a → E150a, e412 → E412
        if re.match(r'^e\d', lower):
            result.append(lower[0].upper() + lower[1:])
            continue

        # 3. Vitamines avec suffixe : b12 → B12, d3 → D3, k2 → K2
        if re.match(r'^[a-z]\d+$', lower):
            result.append(word.upper())
            continue

        # 4. Composé avec préfixe DL- / D- / L- : dl-alpha → DL-Alpha
        dl_match = re.match(r'^(dl|d|l)-(.+)$', lower)
        if dl_match:
            prefix = dl_match.group(1).upper()
            rest = dl_match.group(2).capitalize()
            result.append(f"{prefix}-{rest}")
            continue

        # 5. Petits mots (sauf en position initiale)
        if i > 0 and lower in _LOWERCASE_WORDS:
            result.append(lower)
            continue

        # 6. Cas standard
        result.append(word.capitalize())

    return " ".join(result)


def _humanize_name(slug: str) -> str:
    """
    Convertit un slug en nom lisible avec _smart_title_case.
    Fallback de dernier recours quand aucun text n'est disponible.
    """
    if not slug:
        return slug
    name = slug.replace("-", " ").replace("_", " ")
    return _smart_title_case(name)


def _get_display_name(
    ingredient_id: str,
    text_name_map: dict[str, str],
    taxonomy_en_map: dict[str, str],
    taxonomy_fr_map: dict[str, str] | None = None,
) -> str:
    """
    Retourne le nom lisible d'un ingrédient, par ordre de priorité :
      1. Champ "text" du JSON (source produit) — déjà nettoyé et standardisé
      2. Nom anglais extrait de la taxonomie OFF
      3. Nom français extrait de la taxonomie OFF
      4. Fallback : humanisation du slug
    """
    # 1. Nom du champ text (collecté pendant le flattening)
    if ingredient_id in text_name_map:
        return text_name_map[ingredient_id]

    # 2. Nom taxonomique anglais
    if ingredient_id in taxonomy_en_map:
        return taxonomy_en_map[ingredient_id]

    # 3. Nom taxonomique français
    if taxonomy_fr_map and ingredient_id in taxonomy_fr_map:
        return taxonomy_fr_map[ingredient_id]

    # 4. Fallback : humaniser le slug
    raw = _canonical_name_from_id(ingredient_id)
    return _humanize_name(raw)


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
) -> tuple[dict[str, str], dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """
    Parse une taxonomie OFF texte.

    Retourne :
    - canonical_map         : tag -> canonical_id
    - properties_map        : canonical_id -> dict de propriétés
    - display_name_map      : canonical_id -> nom lisible anglais
    - fr_display_name_map   : canonical_id -> nom lisible français
    """
    canonical_map: dict[str, str] = {}
    properties_map: dict[str, dict[str, str]] = {}
    display_name_map: dict[str, str] = {}
    fr_display_name_map: dict[str, str] = {}

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
                    display_name_map[canonical] = _smart_title_case(values[0].strip())

            if current_canonical:
                if key == "fr" and current_canonical not in fr_display_name_map:
                    fr_display_name_map[current_canonical] = _smart_title_case(values[0].strip())

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
        "Parsed taxonomy: %s canonical ids, %s known tags, %s EN names, %s FR names",
        sum(1 for k, v in canonical_map.items() if k == v),
        len(canonical_map),
        len(display_name_map),
        len(fr_display_name_map),
    )
    return canonical_map, properties_map, display_name_map, fr_display_name_map


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
    """
    Résout l'ingredient_id canonique et extrait le text brut.
    Le ingredient_name sera déterminé plus tard via text_name_map.
    """
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
# Collecte des noms "text" les plus fréquents par ingredient_id
# ---------------------------------------------------------------------------

def _build_text_name_map(text_votes: dict[str, dict[str, int]]) -> dict[str, str]:
    """
    Pour chaque ingredient_id, choisit le text le plus fréquent parmi
    tous les produits, puis applique _smart_title_case.

    text_votes : { ingredient_id: { "raw text": count, ... } }

    Exemple :
        en:sugar → {"sugar": 45, "SUGAR": 12, "Sugar": 30}
        → le plus fréquent est "sugar" (45)
        → après _smart_title_case → "Sugar"
    """
    text_name_map: dict[str, str] = {}

    for ingredient_id, votes in text_votes.items():
        if not votes:
            continue
        # Choisir le text le plus fréquent
        best_text = max(votes, key=votes.get)
        text_name_map[ingredient_id] = _smart_title_case(best_text)

    return text_name_map


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
    text_votes: dict[str, dict[str, int]],
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
        raw_text = normalized["raw_text"]

        # ── Collecter le vote pour le nom "text" ──
        if raw_text:
            if ingredient_id not in text_votes:
                text_votes[ingredient_id] = {}
            text_votes[ingredient_id][raw_text] = (
                text_votes[ingredient_id].get(raw_text, 0) + 1
            )

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
            # sous_ingredient_name sera résolu après le flattening complet
            all_component_rows.append(
                {
                    "ingredient_id": parent_ingredient_id,
                    "sous_ingredient_id": ingredient_id,
                    "raw_text": raw_text,
                    "rang": order,
                }
            )

        # alias
        alias_name = _normalize_alias_text(raw_text)
        if alias_name:
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
                text_votes=text_votes,
                parent_ingredient_id=ingredient_id,
            )


# ---------------------------------------------------------------------------
# Construction tables finales
# ---------------------------------------------------------------------------

def _build_ingredients_table(
    product_rows: list[dict],
    component_rows: list[dict],
    alias_rows: list[dict],
    text_name_map: dict[str, str],
    taxonomy_en_map: dict[str, str],
    taxonomy_fr_map: dict[str, str],
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
            "ingredient_name": _get_display_name(
                ingredient_id, text_name_map, taxonomy_en_map, taxonomy_fr_map
            ),
        }
        for ingredient_id in sorted(ids)
    ]

    return pd.DataFrame(records, columns=["ingredient_id", "ingredient_name"])


def _build_sous_ingredients_df(
    component_rows: list[dict],
    text_name_map: dict[str, str],
    taxonomy_en_map: dict[str, str],
    taxonomy_fr_map: dict[str, str],
) -> pd.DataFrame:
    """
    Construit le DataFrame sous_ingredients avec sous_ingredient_name
    résolu depuis text_name_map (prioritaire) puis taxonomie.
    """
    records = []
    for row in component_rows:
        sous_id = row["sous_ingredient_id"]
        records.append(
            {
                "ingredient_id": row["ingredient_id"],
                "sous_ingredient_id": sous_id,
                "sous_ingredient_name": _get_display_name(
                    sous_id, text_name_map, taxonomy_en_map, taxonomy_fr_map
                ),
                "rang": row["rang"],
            }
        )
    return pd.DataFrame(
        records,
        columns=["ingredient_id", "sous_ingredient_id", "sous_ingredient_name", "rang"],
    )


def _build_alias_df(
    alias_rows: list[dict],
    text_name_map: dict[str, str],
    taxonomy_en_map: dict[str, str],
    taxonomy_fr_map: dict[str, str],
) -> pd.DataFrame:
    """
    Construit le DataFrame alias en filtrant les alias qui correspondent
    exactement au ingredient_name résolu.
    """
    records = []
    for row in alias_rows:
        ingredient_id = row["ingredient_id"]
        alias_name = row["alias_name"]
        display_name = _get_display_name(
            ingredient_id, text_name_map, taxonomy_en_map, taxonomy_fr_map
        )
        # Ne garder l'alias que s'il diffère du nom final
        if alias_name != display_name.lower():
            records.append(
                {
                    "ingredient_id": ingredient_id,
                    "alias_name": alias_name,
                }
            )
    return pd.DataFrame(records, columns=["ingredient_id", "alias_name"])


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

    # 2. Parser taxonomies OFF (noms EN + FR comme fallback)
    ingredients_canonical_map, _, ingredients_en_map, ingredients_fr_map = (
        _parse_taxonomy_with_properties(ingredients_txt)
    )
    _, additives_props, additives_en_map, additives_fr_map = (
        _parse_taxonomy_with_properties(additives_txt)
    )
    additive_classes_canonical_map, _, _, _ = (
        _parse_taxonomy_with_properties(additive_classes_txt)
    )

    # Fusionner les taxonomy display names (fallback seulement)
    taxonomy_en_map = {**ingredients_en_map, **additives_en_map}
    taxonomy_fr_map = {**ingredients_fr_map, **additives_fr_map}

    logger.info(
        f"Taxonomy display names — EN: {len(taxonomy_en_map)}, FR: {len(taxonomy_fr_map)}"
    )

    # 3. Construire role map OFF-only
    additive_role_map = _build_additive_role_map(
        additives_props=additives_props,
        additive_classes_canonical_map=additive_classes_canonical_map,
    )

    # 4. Flatten — collecter text_votes en parallèle
    all_product_rows: list[dict] = []
    all_component_rows: list[dict] = []
    all_alias_rows: list[dict] = []
    text_votes: dict[str, dict[str, int]] = {}

    for _, row in df[["code", "ingredients"]].iterrows():
        _flatten_tree(
            code=row["code"],
            ingredients=row["ingredients"],
            ingredients_canonical_map=ingredients_canonical_map,
            additive_role_map=additive_role_map,
            all_product_rows=all_product_rows,
            all_component_rows=all_component_rows,
            all_alias_rows=all_alias_rows,
            text_votes=text_votes,
            parent_ingredient_id=None,
        )

    logger.info(f"Flattened product ingredient rows: {len(all_product_rows)}")
    logger.info(f"Flattened sous_ingredients rows: {len(all_component_rows)}")
    logger.info(f"Flattened alias rows: {len(all_alias_rows)}")
    logger.info(f"Unique ingredient text votes collected: {len(text_votes)}")

    # 5. Résoudre les noms : text le plus fréquent → smart title case
    text_name_map = _build_text_name_map(text_votes)
    logger.info(f"Text-based display names resolved: {len(text_name_map)}")

    # Log quelques exemples
    for sample_id in list(text_name_map.keys())[:10]:
        votes = text_votes.get(sample_id, {})
        logger.info(
            f"  {sample_id} → '{text_name_map[sample_id]}' "
            f"(votes: {dict(sorted(votes.items(), key=lambda x: -x[1]))})"
        )

    # 6. product_ingredients
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

    # 7. sous_ingredients (noms résolus via text_name_map)
    if all_component_rows:
        df_sous_ingredients = _build_sous_ingredients_df(
            all_component_rows, text_name_map, taxonomy_en_map, taxonomy_fr_map
        )
        df_sous_ingredients = (
            df_sous_ingredients
            .drop_duplicates()
            .sort_values(["ingredient_id", "rang", "sous_ingredient_id"])
            .reset_index(drop=True)
        )
    else:
        df_sous_ingredients = _empty_sous_ingredients_df()

    # 8. alias (filtrés pour exclure les doublons avec le nom final)
    if all_alias_rows:
        df_alias = _build_alias_df(
            all_alias_rows, text_name_map, taxonomy_en_map, taxonomy_fr_map
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
    else:
        df_alias = _empty_alias_df()

    # 9. ingredients (référentiel avec noms résolus)
    df_ingredients = _build_ingredients_table(
        product_rows=all_product_rows,
        component_rows=all_component_rows,
        alias_rows=all_alias_rows,
        text_name_map=text_name_map,
        taxonomy_en_map=taxonomy_en_map,
        taxonomy_fr_map=taxonomy_fr_map,
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

    # 10. Upload S3
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