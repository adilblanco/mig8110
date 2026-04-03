import datetime
from airflow.models import DAG
from airflow.operators.empty import EmptyOperator
from plugins.operators.duckdb_operator import DuckDBOperator
from plugins.operators.custom_kubernetes_operator import CustomKubernetesPodOperator

# Image
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

# Connexions
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

# Base
DATABASE_NAME = "off"
RAW_SCHEMA = "raw"
STAGING_SCHEMA = "staging"

RAW_TABLE_NAME = "canada_products"
STAGING_TABLE_NAME = "source_transformed"
REJECTED_TABLE_NAME = "source_rejected"

PRODUCTS_TABLE_NAME = "products"
INGREDIENTS_TABLE_NAME = "ingredients"
PRODUCT_INGREDIENTS_TABLE_NAME = "product_ingredients"

# S3 keys
RAW_FILE_KEY = f"{DAG_ID}/data.parquet"
FILTERED_FILE_KEY = f"{DAG_ID}/data_filtered.parquet"
VALID_FILE_KEY = f"{DAG_ID}/data_valid.parquet"
INVALID_FILE_KEY = f"{DAG_ID}/data_invalid.parquet"
TRANSFORMED_FILE_KEY = f"{DAG_ID}/data_transformed.parquet"

FILTER_COLUMNS = ",".join([
    "code", "brands", "product_name", "product_quantity", "product_quantity_unit",
    "quantity", "serving_quantity", "serving_size", "categories_tags", "countries_tags",
    "ecoscore_score", "ecoscore_grade", "images", "ingredients_n", "ingredients",
    "nutriscore_score", "nutriscore_grade", "nutriments",
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

    extract_data = CustomKubernetesPodOperator(
        dag=dag,
        task_id="extract-data",
        name="extract-data",
        image=IMAGE,
        env_vars=s3_env_vars,
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
        env_vars=s3_env_vars,
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
        env_vars=s3_env_vars,
        arguments=[
            "--command", "transform_data",
            "--input_file_key", VALID_FILE_KEY,
            "--output_file_key", TRANSFORMED_FILE_KEY,
        ],
    )

    load_silver = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-silver",
        name="load-silver",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", TRANSFORMED_FILE_KEY,
            "--table_name", STAGING_TABLE_NAME,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    create_products_table = DuckDBOperator(
        dag=dag,
        task_id="create-products-table",
        sql=f"""
            CREATE OR REPLACE TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCTS_TABLE_NAME} AS
            SELECT
                code,
                product_name,
                brands,
                quantity,
                serving_size,
                ecoscore_score,
                ecoscore_grade,
                nutriscore_score,
                nutriscore_grade,
                front_url,
                ingredients_url,
                nutrition_url,
                energy_kcal_100g,
                fat_100g,
                saturated_fat_100g,
                trans_fat_100g,
                cholesterol_100g,
                sodium_100g,
                salt_100g,
                carbohydrates_100g,
                fiber_100g,
                sugars_100g,
                proteins_100g,
                calcium_100g,
                iron_100g,
                potassium_100g
            FROM {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_TABLE_NAME}
            WHERE code IS NOT NULL;
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_ingredients_table = DuckDBOperator(
        dag=dag,
        task_id="create-ingredients-table",
        sql=f"""
            CREATE OR REPLACE TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{INGREDIENTS_TABLE_NAME} AS
            WITH RECURSIVE ingredient_nodes AS (
                SELECT
                    s.code,
                    CAST(je.key AS INTEGER) + 1 AS ingredient_order,
                    0 AS ingredient_level,
                    CAST(NULL AS VARCHAR) AS parent_ingredient_id,
                    je.value AS ingredient_json
                FROM {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_TABLE_NAME} s,
                     json_each(CAST(s.ingredients AS JSON)) je
                WHERE s.code IS NOT NULL
                  AND s.ingredients IS NOT NULL

                UNION ALL

                SELECT
                    n.code,
                    CAST(child.key AS INTEGER) + 1 AS ingredient_order,
                    n.ingredient_level + 1 AS ingredient_level,
                    json_extract_string(n.ingredient_json, '$.id') AS parent_ingredient_id,
                    child.value AS ingredient_json
                FROM ingredient_nodes n,
                     json_each(json_extract(n.ingredient_json, '$.ingredients')) child
                WHERE json_extract(n.ingredient_json, '$.ingredients') IS NOT NULL
            ),
            extracted AS (
                SELECT
                    json_extract_string(ingredient_json, '$.id') AS ingredient_id,
                    json_extract_string(ingredient_json, '$.text') AS ingredient_text_raw,
                    TRY_CAST(json_extract_string(ingredient_json, '$.is_in_taxonomy') AS INTEGER) AS is_in_taxonomy,
                    json_extract_string(ingredient_json, '$.vegan') AS vegan,
                    json_extract_string(ingredient_json, '$.vegetarian') AS vegetarian,
                    json_extract_string(ingredient_json, '$.from_palm_oil') AS from_palm_oil,
                    json_extract_string(ingredient_json, '$.processing') AS processing,
                    json_extract_string(ingredient_json, '$.labels') AS labels,
                    CASE
                        WHEN json_extract(ingredient_json, '$.ingredients') IS NOT NULL
                             AND json_array_length(json_extract(ingredient_json, '$.ingredients')) > 0
                        THEN 1 ELSE 0
                    END AS is_compound_ingredient
                FROM ingredient_nodes
            ),
            normalized AS (
                SELECT
                    ingredient_id,
                    lower(
                        trim(
                            regexp_replace(
                                regexp_replace(
                                    regexp_replace(
                                        regexp_replace(
                                            coalesce(
                                                regexp_replace(ingredient_id, '^[a-z]{{2}}:', ''),
                                                ingredient_text_raw
                                            ),
                                            '[_"]',
                                            ' '
                                        ),
                                        '[-/]',
                                        ' '
                                    ),
                                    '\\s+',
                                    ' '
                                ),
                                '[^a-zA-Z0-9 %]+',
                                ''
                            )
                        )
                    ) AS ingredient_name,
                    is_in_taxonomy,
                    vegan,
                    vegetarian,
                    from_palm_oil,
                    processing,
                    labels,
                    is_compound_ingredient
                FROM extracted
                WHERE ingredient_id IS NOT NULL
            )
            SELECT DISTINCT
                ingredient_id,
                ingredient_name,
                is_in_taxonomy,
                vegan,
                vegetarian,
                from_palm_oil,
                processing,
                labels,
                is_compound_ingredient,
                CASE
                    WHEN ingredient_name IS NULL OR trim(ingredient_name) = '' THEN 1
                    WHEN ingredient_name LIKE '%contains less than%' THEN 1
                    WHEN ingredient_name LIKE '%may contain%' THEN 1
                    WHEN ingredient_name LIKE '%manufactured in%' THEN 1
                    WHEN ingredient_name LIKE '%facility that also processes%' THEN 1
                    WHEN ingredient_name LIKE '%daily value%' THEN 1
                    WHEN ingredient_name LIKE '%polyunsaturated fat%' THEN 1
                    WHEN ingredient_name LIKE '%monounsaturated fat%' THEN 1
                    WHEN ingredient_name LIKE '%cholesterol%' THEN 1
                    WHEN ingredient_name LIKE '%sodium%' THEN 1
                    WHEN ingredient_name LIKE '%total carbohydrate%' THEN 1
                    WHEN ingredient_name LIKE '%dietary fiber%' THEN 1
                    WHEN ingredient_name LIKE '%total sugars%' THEN 1
                    WHEN ingredient_name LIKE '%vitamin d%' THEN 1
                    WHEN ingredient_name LIKE '%potassium%' THEN 1
                    WHEN length(ingredient_name) > 120 THEN 1
                    ELSE 0
                END AS is_probable_noise
            FROM normalized
            WHERE ingredient_id IS NOT NULL;
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_product_ingredients_table = DuckDBOperator(
        dag=dag,
        task_id="create-product-ingredients-table",
        sql=f"""
            CREATE OR REPLACE TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCT_INGREDIENTS_TABLE_NAME} AS
            WITH RECURSIVE ingredient_nodes AS (
                SELECT
                    s.code,
                    CAST(je.key AS INTEGER) + 1 AS ingredient_order,
                    0 AS ingredient_level,
                    CAST(NULL AS VARCHAR) AS parent_ingredient_id,
                    je.value AS ingredient_json
                FROM {DATABASE_NAME}.{STAGING_SCHEMA}.{STAGING_TABLE_NAME} s,
                     json_each(CAST(s.ingredients AS JSON)) je
                WHERE s.code IS NOT NULL
                  AND s.ingredients IS NOT NULL

                UNION ALL

                SELECT
                    n.code,
                    CAST(child.key AS INTEGER) + 1 AS ingredient_order,
                    n.ingredient_level + 1 AS ingredient_level,
                    json_extract_string(n.ingredient_json, '$.id') AS parent_ingredient_id,
                    child.value AS ingredient_json
                FROM ingredient_nodes n,
                     json_each(json_extract(n.ingredient_json, '$.ingredients')) child
                WHERE json_extract(n.ingredient_json, '$.ingredients') IS NOT NULL
            )
            SELECT
                code,
                json_extract_string(ingredient_json, '$.id') AS ingredient_id,
                ingredient_order,
                ingredient_level,
                parent_ingredient_id,
                TRY_CAST(json_extract_string(ingredient_json, '$.percent') AS DOUBLE) AS percent,
                TRY_CAST(json_extract_string(ingredient_json, '$.percent_min') AS DOUBLE) AS percent_min,
                TRY_CAST(json_extract_string(ingredient_json, '$.percent_max') AS DOUBLE) AS percent_max,
                TRY_CAST(json_extract_string(ingredient_json, '$.percent_estimate') AS DOUBLE) AS percent_estimate
            FROM ingredient_nodes
            WHERE json_extract_string(ingredient_json, '$.id') IS NOT NULL;
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_constraints = DuckDBOperator(
        dag=dag,
        task_id="create-constraints",
        sql=f"""
            ALTER TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCTS_TABLE_NAME}
            ADD CONSTRAINT pk_products PRIMARY KEY (code);

            ALTER TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{INGREDIENTS_TABLE_NAME}
            ADD CONSTRAINT pk_ingredients PRIMARY KEY (ingredient_id);

            ALTER TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCT_INGREDIENTS_TABLE_NAME}
            ADD CONSTRAINT pk_product_ingredients
            PRIMARY KEY (code, ingredient_id, ingredient_order, ingredient_level);

            ALTER TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCT_INGREDIENTS_TABLE_NAME}
            ADD CONSTRAINT fk_product_ingredients_product
            FOREIGN KEY (code)
            REFERENCES {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCTS_TABLE_NAME}(code);

            ALTER TABLE {DATABASE_NAME}.{STAGING_SCHEMA}.{PRODUCT_INGREDIENTS_TABLE_NAME}
            ADD CONSTRAINT fk_product_ingredients_ingredient
            FOREIGN KEY (ingredient_id)
            REFERENCES {DATABASE_NAME}.{STAGING_SCHEMA}.{INGREDIENTS_TABLE_NAME}(ingredient_id);
        """,
        duckdb_conn_id="duckdb_default",
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

    start >> create_schemas >> extract_data >> filter_data >> load_bronze >> validate_data >> transform_data >> load_silver

    load_silver >> create_products_table
    load_silver >> create_ingredients_table
    load_silver >> create_product_ingredients_table
    load_silver >> load_rejected

    [create_products_table, create_ingredients_table, create_product_ingredients_table] >> create_constraints
    [create_constraints, load_rejected] >> end