"""
DAG : off_initial_load
======================
Chargement initial complet des produits alimentaires canadiens depuis Open Food Facts.

Pipeline :
    extract_data             : Télécharge le snapshot parquet depuis GitHub et le dépose sur S3
    filter_data              : Sélectionne les colonnes utiles
    load_bronze              : Charge les données filtrées dans off.raw.canada_products
    validate_data            : Sépare les enregistrements valides et invalides
    transform_data           : Produit les jeux de données normalisés :
                               - produits
                               - ingrédients détaillés
                               - tags d’ingrédients
                               - analyse d’ingrédients
    load_silver_products     : Charge les produits transformés
    load_silver_ingredients  : Charge les ingrédients détaillés
    load_silver_tags         : Charge les tags d’ingrédients
    load_silver_analysis     : Charge les analyses d’ingrédients
    load_rejected            : Charge les enregistrements invalides
"""

import datetime
from airflow.models import DAG
from airflow.operators.empty import EmptyOperator
from plugins.operators.duckdb_operator import DuckDBOperator
from plugins.operators.custom_kubernetes_operator import CustomKubernetesPodOperator


IMAGE = "mig8110/etl-images:1.0.0"
DAG_ID = "off_initial_load"

args = {
    "owner": "airflow",
    "start_date": datetime.datetime(2026, 1, 1),
    "email_on_failure": True,
    "retries": 1,
    "retry_delay": datetime.timedelta(minutes=60),
}

dag = DAG(
    dag_id=DAG_ID,
    default_args=args,
    schedule_interval=None,
    catchup=False,
    tags=["mig8110", "off"],
)

# -------------------------------------------------------------------
# Connexions
# -------------------------------------------------------------------
s3_env_vars = {
    "S3_ENDPOINT": "{{ conn.s3_conn.host }}",
    "S3_ACCESS_KEY": "{{ conn.s3_conn.login }}",
    "S3_SECRET_KEY": "{{ conn.s3_conn.password }}",
    "S3_BUCKET": "{{ conn.s3_conn.schema }}",
}

duckdb_env_vars = {
    "DUCKDB_TOKEN": "{{ conn.duckdb_default.password }}",
    "DUCKDB_DB": "{{ conn.duckdb_default.schema }}",
}

airflow_env_vars = {
    "AIRFLOW_CTX_DAG_RUN_ID": "{{ run_id }}",
}

# -------------------------------------------------------------------
# Schémas / tables
# -------------------------------------------------------------------
DATABASE_NAME = "off"
RAW_SCHEMA = "raw"
STAGING_SCHEMA = "staging"

RAW_TABLE_NAME = "canada_products"
STAGING_PRODUCTS_TABLE = "source_transformed"
STAGING_INGREDIENTS_TABLE = "product_ingredients"
STAGING_INGREDIENT_TAGS_TABLE = "product_ingredient_tags"
STAGING_INGREDIENT_ANALYSIS_TABLE = "product_ingredient_analysis"
REJECTED_TABLE_NAME = "source_rejected"

# -------------------------------------------------------------------
# Fichiers S3
# -------------------------------------------------------------------
RAW_FILE_KEY = f"{DAG_ID}/data.parquet"
FILTERED_FILE_KEY = f"{DAG_ID}/data_filtered.parquet"
VALID_FILE_KEY = f"{DAG_ID}/data_valid.parquet"
INVALID_FILE_KEY = f"{DAG_ID}/data_invalid.parquet"

TRANSFORMED_PRODUCTS_FILE_KEY = f"{DAG_ID}/data_transformed_products.parquet"
TRANSFORMED_INGREDIENTS_FILE_KEY = f"{DAG_ID}/data_transformed_ingredients.parquet"
TRANSFORMED_INGREDIENT_TAGS_FILE_KEY = f"{DAG_ID}/data_transformed_ingredient_tags.parquet"
TRANSFORMED_INGREDIENT_ANALYSIS_FILE_KEY = f"{DAG_ID}/data_transformed_ingredient_analysis.parquet"

# -------------------------------------------------------------------
# Colonnes source à conserver
# -------------------------------------------------------------------
FILTER_COLUMNS = ",".join([
    "code",
    "brands",
    "product_name",
    "product_quantity",
    "product_quantity_unit",
    "quantity",
    "serving_quantity",
    "serving_size",
    "categories_tags",
    "countries_tags",
    "ecoscore_score",
    "ecoscore_grade",
    "images",
    "ingredients_tags",
    "ingredients_original_tags",
    "ingredients",
    "ingredients_analysis_tags",
    "ingredients_percent_analysis",
    "ingredients_from_palm_oil_n",
    "ingredients_n",
    "nutriscore_score",
    "nutriscore_grade",
    "nutriments",
])

with dag:
    start = EmptyOperator(task_id="start")

    create_schemas = DuckDBOperator(
        dag=dag,
        task_id="create-schemas",
        sql=f"""
            CREATE SCHEMA IF NOT EXISTS {DATABASE_NAME}.{RAW_SCHEMA};
            CREATE SCHEMA IF NOT EXISTS {DATABASE_NAME}.{STAGING_SCHEMA};
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_target_tables = DuckDBOperator(
        dag=dag,
        task_id="create-target-tables",
        sql=f"""
            CREATE TABLE IF NOT EXISTS {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_PRODUCTS_TABLE} (
                code VARCHAR,
                brands VARCHAR,
                product_name VARCHAR,
                product_name_normalized VARCHAR,
                product_quantity DOUBLE,
                product_quantity_unit VARCHAR,
                quantity VARCHAR,
                serving_quantity DOUBLE,
                serving_size VARCHAR,
                category_last_tag VARCHAR,
                ecoscore_score DOUBLE,
                ecoscore_grade VARCHAR,
                nutriscore_score DOUBLE,
                nutriscore_grade VARCHAR,
                ingredient_count INTEGER,
                ingredient_from_palm_oil_count INTEGER,
                ingredient_percent_analysis_score DOUBLE,
                image_front_url VARCHAR,
                image_thumb_url VARCHAR
            );

            CREATE TABLE IF NOT EXISTS {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_INGREDIENTS_TABLE} (
                product_code VARCHAR,
                ingredient_order INTEGER,
                ingredient_id_raw VARCHAR,
                ingredient_id_normalized VARCHAR,
                ingredient_text_raw VARCHAR,
                ingredient_text_normalized VARCHAR,
                ingredient_display_name VARCHAR,
                vegan VARCHAR,
                vegetarian VARCHAR,
                percent DOUBLE,
                percent_min DOUBLE,
                percent_max DOUBLE,
                percent_estimate DOUBLE,
                from_palm_oil VARCHAR,
                is_in_taxonomy INTEGER
            );

            CREATE TABLE IF NOT EXISTS {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_INGREDIENT_TAGS_TABLE} (
                product_code VARCHAR,
                tag_source VARCHAR,
                tag_order INTEGER,
                tag_raw VARCHAR,
                tag_normalized VARCHAR,
                is_generic BOOLEAN,
                is_specific BOOLEAN
            );

            CREATE TABLE IF NOT EXISTS {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_INGREDIENT_ANALYSIS_TABLE} (
                product_code VARCHAR,
                ingredient_count INTEGER,
                ingredient_from_palm_oil_count INTEGER,
                ingredient_percent_analysis_score DOUBLE,
                analysis_tag_order INTEGER,
                analysis_tag_raw VARCHAR,
                analysis_tag_normalized VARCHAR
            );
        """,
        duckdb_conn_id="duckdb_default",
    )

    extract_data = CustomKubernetesPodOperator(
        dag=dag,
        task_id="extract-data",
        name="extract-data",
        image=IMAGE,
        env_vars={**s3_env_vars},
        arguments=[
            "--command", "extract_data",
            "--output_file_key", RAW_FILE_KEY,
            "--url", "https://raw.githubusercontent.com/adilblanco/mig8110/main/data/canada_products.parquet.zip",
        ],
    )

    filter_data = CustomKubernetesPodOperator(
        dag=dag,
        task_id="filter-data",
        name="filter-data",
        image=IMAGE,
        env_vars={**s3_env_vars},
        arguments=[
            "--command", "filter_data",
            "--input_file_key", RAW_FILE_KEY,
            "--output_file_key", FILTERED_FILE_KEY,
            "--columns", FILTER_COLUMNS,
        ],
    )

    load_bronze = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-bronze",
        name="load-bronze",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", FILTERED_FILE_KEY,
            "--table_name", RAW_TABLE_NAME,
            "--schema_name", f"{DATABASE_NAME}.{RAW_SCHEMA}",
        ],
    )

    validate_data = CustomKubernetesPodOperator(
        dag=dag,
        task_id="validate-data",
        name="validate-data",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars, **airflow_env_vars},
        arguments=[
            "--command", "validate_data",
            "--input_file_key", FILTERED_FILE_KEY,
            "--output_file_key", VALID_FILE_KEY,
            "--invalid_file_key", INVALID_FILE_KEY,
        ],
    )

    transform_data = CustomKubernetesPodOperator(
        dag=dag,
        task_id="transform-data",
        name="transform-data",
        image=IMAGE,
        env_vars={**s3_env_vars},
        arguments=[
            "--command", "transform_data",
            "--input_file_key", VALID_FILE_KEY,
            "--products_output_file_key", TRANSFORMED_PRODUCTS_FILE_KEY,
            "--ingredients_output_file_key", TRANSFORMED_INGREDIENTS_FILE_KEY,
            "--ingredient_tags_output_file_key", TRANSFORMED_INGREDIENT_TAGS_FILE_KEY,
            "--ingredient_analysis_output_file_key", TRANSFORMED_INGREDIENT_ANALYSIS_FILE_KEY,
        ],
    )

    load_silver_products = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-silver-products",
        name="load-silver-products",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", TRANSFORMED_PRODUCTS_FILE_KEY,
            "--table_name", STAGING_PRODUCTS_TABLE,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    load_silver_ingredients = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-silver-ingredients",
        name="load-silver-ingredients",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", TRANSFORMED_INGREDIENTS_FILE_KEY,
            "--table_name", STAGING_INGREDIENTS_TABLE,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    load_silver_tags = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-silver-tags",
        name="load-silver-tags",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", TRANSFORMED_INGREDIENT_TAGS_FILE_KEY,
            "--table_name", STAGING_INGREDIENT_TAGS_TABLE,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    load_silver_analysis = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-silver-analysis",
        name="load-silver-analysis",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", TRANSFORMED_INGREDIENT_ANALYSIS_FILE_KEY,
            "--table_name", STAGING_INGREDIENT_ANALYSIS_TABLE,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    load_rejected = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-rejected",
        name="load-rejected",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", INVALID_FILE_KEY,
            "--table_name", REJECTED_TABLE_NAME,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    end = EmptyOperator(task_id="end")

    (
        start
        >> create_schemas
        >> create_target_tables
        >> extract_data
        >> filter_data
        >> load_bronze
        >> validate_data
        >> transform_data
        >> [
            load_silver_products,
            load_silver_ingredients,
            load_silver_tags,
            load_silver_analysis,
            load_rejected,
        ]
        >> end
    )