import os
import json
import logging
import requests
import pandas as pd
import numpy as np
from common.s3 import S3FileHandler

logger = logging.getLogger(__name__)

# URL de la taxonomie officielle des ingrédients depuis OpenFoodFacts
INGREDIENTS_TXT_URL = (
    "https://raw.githubusercontent.com/openfoodfacts/"
    "openfoodfacts-server/main/taxonomies/food/ingredients.txt"
)


# ---------------------------------------------------------------------------
# 1. Téléchargement du fichier de référence OFF
# ---------------------------------------------------------------------------

def _download_ingredients_txt(url: str) -> str:
    """Télécharge la taxonomie des ingrédients depuis OpenFoodFacts."""
    logger.info(f"Downloading ingredients taxonomy from {url}...")
    session = requests.Session()
    session.headers.update({"User-Agent": "FoodHealthAdvisor/1.0"})
    response = session.get(url, timeout=60)
    response.raise_for_status()  # Lève une exception en cas d'erreur HTTP
    return response.text


# ---------------------------------------------------------------------------
# 2. Helpers généraux
# ---------------------------------------------------------------------------

def _is_null(value) -> bool:
    """Vérifie si une valeur est nulle (None, NaN)."""
    return value is None or (isinstance(value, float) and np.isnan(value))


def _slugify(value: str) -> str:
    """Convertit une chaîne en format slug (lowercase, tirets pour espaces)."""
    return value.strip().lower().replace(" ", "-")


def _is_language_code(lang: str) -> bool:
    """Vérifie si une chaîne est un code de langue valide (ex: 'en', 'fr')."""
    return lang.isalpha() and 2 <= len(lang) <= 3


def _parse_ingredients_value(value):
    """
    Convertit la colonne ingredients en liste Python.
    Gère les cas : liste, JSON string, ou null.
    Retour : toujours une liste (vide si conversion échoue).
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
            # Ne retourner que si c'est une liste
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            logger.warning(f"Impossible de parser ingredients: {value[:120]}")
            return []

    return []


# ---------------------------------------------------------------------------
# 3. Parsing enrichi de la taxonomie OFF
# ---------------------------------------------------------------------------

def _parse_taxonomy(text: str) -> tuple[dict, dict]:
    """
    Parse le fichier texte de taxonomie OFF pour extraire :
    - canonical_map : mappe chaque tag (en:ingredient, fr:ingredient) vers son ID canonical
    - ingredient_props : propriétés de chaque ingrédient (vegan, vegetarian, from_palm_oil)
    
    Retour : (canonical_map, ingredient_props)
    """
    canonical_map: dict[str, str] = {}  # Tag → ID canonical
    ingredient_props: dict[str, dict] = {}  # ID canonical → propriétés

    current_canonical: str | None = None

    def _flush():
        """Réinitialise l'ingrédient courant."""
        nonlocal current_canonical
        current_canonical = None

    def _to_tag(lang: str, value: str) -> str:
        """Formate un tag du style 'en:ingredient-name'."""
        return f"{lang}:{_slugify(value)}"

    def _canonical_name_from_id(ingredient_id: str) -> str:
        """Extrait le nom canonical depuis l'ID (ex: 'en:water' → 'water')."""
        return ingredient_id.split(":", 1)[1] if ":" in ingredient_id else ingredient_id

    def _ensure_props(ingredient_id: str):
        """S'assure que l'ingrédient a une entrée dans ingredient_props."""
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
        """Convertit une propriété texte en booléen ou None."""
        val = value.strip().lower()
        if val in {"yes", "true"}:
            return True
        if val in {"no", "false"}:
            return False
        if val in {"maybe", "unknown", "sometimes", ""}:
            return None
        return None

    # Parcourrir chaque ligne du fichier
    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Ignorer les lignes vides et les commentaires
        if not line or line.startswith("#"):
            _flush()
            continue

        # Ignorer les sections indésirables
        if line.startswith(("stopwords:", "synonyms:", "< ")):
            continue

        # Chercher le séparateur ':'
        if ":" not in line:
            continue

        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.strip()

        # Traiter les codes de langue (en, fr, etc.) → on stocke les variantes
        if _is_language_code(key):
            values = [v.strip() for v in rest.split(",") if v.strip()]
            if not values:
                continue

            # Si c'est la première langue (en), créer le canonical
            if current_canonical is None and key == "en":
                current_canonical = _to_tag(key, values[0])
                canonical_map[current_canonical] = current_canonical
                _ensure_props(current_canonical)

            # Mapper tous les tags vers le canonical
            if current_canonical:
                for val in values:
                    canonical_map.setdefault(_to_tag(key, val), current_canonical)

            continue

        # Traiter les propriétés (vegan, vegetarian, etc.) de l'ingrédient courant
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
# 4. Matching d'un ingrédient OFF
# ---------------------------------------------------------------------------

def _candidate_tags_from_ingredient(item: dict) -> list[str]:
    """
    Génère une liste de tags possibles pour un ingrédient.
    Utilisé pour matcher avec la taxonomie.
    """
    candidates = []

    # Candidat 1 : ID fourni dans les données
    ingredient_id = item.get("id")
    if isinstance(ingredient_id, str) and ingredient_id.strip():
        candidates.append(ingredient_id.strip().lower())

    # Candidats 2-3 : Texte en anglais et français
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        slug = _slugify(text)
        candidates.extend([
            f"en:{slug}",
            f"fr:{slug}",
        ])

    return candidates


def _canonical_name_from_id(ingredient_id: str) -> str:
    """Extrait le nom canonical depuis l'ID."""
    return ingredient_id.split(":", 1)[1] if ":" in ingredient_id else ingredient_id


def _normalize_ingredient(item: dict, canonical_map: dict, ingredient_props: dict) -> dict | None:
    """
    Normalise un ingrédient en le recherchant dans la taxonomie.
    Si trouvé : retourne ses propriétés depuis ingredient_props.
    Si non trouvé : crée un nouvel ID avec les info disponibles et marque is_in_taxonomy=False.
    """
    if not isinstance(item, dict):
        return None

    # Extraire le texte de l'ingrédient
    ingredient_text = item.get("text")
    ingredient_text = ingredient_text.strip() if isinstance(ingredient_text, str) and ingredient_text.strip() else None

    # Essayer de matcher avec la taxonomie
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

    # Fallback : créer une nouvelle entrée non validée
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
    """
    Aplatit une structure d'ingrédients hiérarchisée (arbre) en liste plate.
    Gère les enfants (ingredients imbriqués) en augmentant le level.
    
    Retour : liste de dictionnaires avec code, id, text, order, level, parent_id, etc.
    """
    rows = []

    ingredients = _parse_ingredients_value(ingredients)

    if not ingredients:
        return rows

    # Boucler sur chaque ingrédient avec son ordre
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
            "ingredient_order": order,  # Position dans la liste
            "ingredient_level": level,  # Profondeur (0 = root)
            "parent_ingredient_id": parent_ingredient_id,
            "ingredient_name": normalized["ingredient_name"],
            "is_in_taxonomy": normalized["is_in_taxonomy"],
            "vegan": normalized["vegan"],
            "vegetarian": normalized["vegetarian"],
            "from_palm_oil": normalized["from_palm_oil"],
        }
        rows.append(row)

        # Traiter les ingrédients enfants de manière récursive
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
    """
    Crée une table deduplicatée des ingrédients uniques.
    Retour : DataFrame avec colonnes ingredient_id, name, props, etc.
    """
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
        .drop_duplicates(subset=["ingredient_id"])  # Un seul ingrédient par ID
        .sort_values("ingredient_id")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 7. Point d'entrée principal
# ---------------------------------------------------------------------------

def handle(
    input_file_key: str,
    ingredients_output_key: str,
    product_ingredients_output_key: str,
) -> None:
    """
    Ordonnatrice principale : télécharge la taxonomie, lit le fichier d'entrée,
    normalise les ingrédients et envoie deux tables vers S3.
    """
    # Récupérer les variables d'environnement S3
    s3_bucket = os.environ["S3_BUCKET"]
    s3_endpoint = os.environ["S3_ENDPOINT"]
    s3_access_key = os.environ["S3_ACCESS_KEY"]
    s3_secret_key = os.environ["S3_SECRET_KEY"]

    logger.info(f"Normalizing ingredients from {input_file_key}...")

    s3_handler = S3FileHandler(s3_bucket, s3_endpoint, s3_access_key, s3_secret_key)

    # Télécharger et lire les données d'entrée
    raw = s3_handler.download_to_memory(input_file_key)
    df = pd.read_parquet(raw)

    # Vérifier la présence de la colonne 'ingredients'
    if "ingredients" not in df.columns:
        logger.error(
            "COLUMN 'ingredients' NOT FOUND IN PARQUET. "
            f"Available columns: {df.columns.tolist()}"
        )
        # Créer des tables vides si erreur
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

    # Diagnostiquer la colonne (type, nulls, exemples)
    col = df["ingredients"]
    sample = col.dropna().head(3)
    logger.info(
        f"[DIAG] ingredients — dtype={col.dtype} | "
        f"non-null={col.notna().sum()}/{len(df)} | "
        f"sample types={[type(v).__name__ for v in sample]} | "
        f"sample values={[repr(v)[:120] for v in sample]}"
    )

    # Télécharger et parser la taxonomie OFF
    ingredients_txt = _download_ingredients_txt(INGREDIENTS_TXT_URL)
    canonical_map, ingredient_props = _parse_taxonomy(ingredients_txt)

    # Aplatir les ingrédients pour chaque produit
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

    # Créer le DataFrame complet
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

    logger.info(f"df_full shape: {df_full.shape}")
    if not df_full.empty:
        logger.info("df_full head(10):\n" + df_full.head(10).to_string())
        logger.info("df_full dtypes:\n" + df_full.dtypes.to_string())
    else:
        logger.warning("df_full is empty after flattening")

    # Dédupliquer si nécessaire
    if not df_full.empty:
        df_full = df_full.drop_duplicates().reset_index(drop=True)

    # Table 1 : ingrédients uniques (de référence)
    df_ingredients = _build_ingredients_table(df_full)

    # Table 2 : association produit-ingrédients (avec hiérarchie et ordre)
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

    logger.info(f"df_ingredients shape: {df_ingredients.shape}")
    logger.info(f"df_product_ingredients shape: {df_product_ingredients.shape}")

    if not df_ingredients.empty:
        logger.info("df_ingredients head(10):\n" + df_ingredients.head(10).to_string())

    if not df_product_ingredients.empty:
        logger.info("df_product_ingredients head(10):\n" + df_product_ingredients.head(10).to_string())

    # Envoyer les deux tables vers S3
    s3_handler.upload_dataframe(df_ingredients, ingredients_output_key)
    logger.info(
        f"ingredients uploaded → {ingredients_output_key} ({len(df_ingredients)} records)"
    )

    s3_handler.upload_dataframe(df_product_ingredients, product_ingredients_output_key)
    logger.info(
        f"product_ingredients uploaded → {product_ingredients_output_key} ({len(df_product_ingredients)} records)"
    )