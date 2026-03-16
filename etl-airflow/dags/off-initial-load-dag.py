import datetime
from airflow.models import DAG
from airflow.operators.empty import EmptyOperator
from plugins.operators.duckdb_operator import DuckDBOperator
from plugins.operators.custom_kubernetes_operator import CustomKubernetesPodOperator


args = {
    "owner": "airflow",
    "start_date": datetime.datetime(2026, 1, 1),
    "email_on_failure": True,
    "retries": 1,
    "retry_delay": datetime.timedelta(minutes=60),
}

dag = DAG(
    dag_id="off_initial_load",
    default_args=args,
    schedule_interval=None,
    catchup=False,
    tags=["mig8110", "off"],
)

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

SCHEMA_NAME = "off"
RAW_TABLE_NAME = "canada_products"
NUTRITIONS_TABLE_NAME = "nutritions"
PRODUCT_COVERS_TABLE_NAME = "product_covers"
PRODUCTS_TABLE_NAME = "products"

INGREDIENTS_TO_FILTER = [
    "added sugar",
    "disaccharide",
    "monosaccharide",
    "polysaccharide",
    "carbohydrate",
    "dairy",
    "milk product",
    "milk products",
    "compound",
    "compound ingredient",
    "preparation",
]

FILTER_LIST_SQL = ", ".join([f"'{item}'" for item in INGREDIENTS_TO_FILTER])

with dag:

    start = EmptyOperator(task_id="start")

    create_schema = DuckDBOperator(
        dag=dag,
        task_id="create-schema",
        sql=f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}",
        duckdb_conn_id="duckdb_default",
    )

    extract_data = CustomKubernetesPodOperator(
        dag=dag,
        name="extract-data",
        image="mig8110/etl-images:1.0.0",
        env_vars={**s3_env_vars},
        arguments=[
            "--command", "extract_data",
            "--output_file_key", "data.parquet",
            "--url", "https://raw.githubusercontent.com/adilblanco/mig8110/main/data/canada_products.parquet.zip",
        ],
    )

    load_data = CustomKubernetesPodOperator(
        dag=dag,
        name="load-data",
        image="mig8110/etl-images:1.0.0",
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", "data.parquet",
            "--table_name", RAW_TABLE_NAME,
        ],
    )

    move_raw_table_to_off = DuckDBOperator(
        dag=dag,
        task_id="move-raw-table-to-off",
        sql=f"""
        CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};

        CREATE OR REPLACE TABLE {SCHEMA_NAME}.{RAW_TABLE_NAME} AS
        SELECT *
        FROM main.{RAW_TABLE_NAME};
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_nutritions_table = DuckDBOperator(
        dag=dag,
        task_id="create-nutritions-table",
        sql=f"""
        CREATE OR REPLACE TABLE {SCHEMA_NAME}.{NUTRITIONS_TABLE_NAME} AS
        SELECT
            code,
            n.name,
            n.value,
            n."100g" AS value_100g,
            n.serving AS value_serving,
            n.unit
        FROM {SCHEMA_NAME}.{RAW_TABLE_NAME}
        CROSS JOIN UNNEST(nutriments) AS t(n)
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_product_covers_table = DuckDBOperator(
        dag=dag,
        task_id="create-product-covers-table",
        sql=f"""
        CREATE OR REPLACE TABLE {SCHEMA_NAME}.{PRODUCT_COVERS_TABLE_NAME} AS
        SELECT
            CAST(code AS VARCHAR) AS code_str,
            CONCAT(
                'https://images.openfoodfacts.org/images/products/',
                SUBSTR(LPAD(CAST(code AS VARCHAR), 13, '0'), 1, 3), '/',
                SUBSTR(LPAD(CAST(code AS VARCHAR), 13, '0'), 4, 3), '/',
                SUBSTR(LPAD(CAST(code AS VARCHAR), 13, '0'), 7, 3), '/',
                SUBSTR(LPAD(CAST(code AS VARCHAR), 13, '0'), 10, 4), '/',
                'front_en.',
                (list_filter(images, x -> x.key = 'front_en')[1].rev)::INTEGER,
                '.400.jpg'
            ) AS url_front_en_400px
        FROM {SCHEMA_NAME}.{RAW_TABLE_NAME}
        WHERE array_length(list_filter(images, x -> x.key = 'front_en')) > 0
        """,
        duckdb_conn_id="duckdb_default",
    )

    create_products_table = DuckDBOperator(
        dag=dag,
        task_id="create-products-table",
        sql=f"""
        CREATE OR REPLACE TABLE {SCHEMA_NAME}.{PRODUCTS_TABLE_NAME} AS
        WITH source_data AS (
            SELECT
                code,
                product_name,
                brands,
                categories,
                categories_tags,
                nutriscore_score,
                nutriscore_grade,

                CASE
                    WHEN ingredients_original_tags IS NOT NULL
                         AND array_length(ingredients_original_tags) > 0
                    THEN ingredients_original_tags
                    WHEN ingredients_tags IS NOT NULL
                         AND array_length(ingredients_tags) > 0
                    THEN ingredients_tags
                    ELSE []
                END AS raw_tags

            FROM {SCHEMA_NAME}.{RAW_TABLE_NAME}
        ),
        normalized_data AS (
            SELECT
                code,
                product_name,
                brands,
                categories,
                categories_tags,
                nutriscore_score,
                nutriscore_grade,

                list_filter(
                    list_transform(
                        raw_tags,
                        x -> replace(
                            regexp_replace(lower(x), '^[a-z]+:', ''),
                            '-',
                            ' '
                        )
                    ),
                    x -> x NOT IN ({FILTER_LIST_SQL})
                ) AS normalized_ingredients

            FROM source_data
        )
        SELECT
            code,
            product_name[1].text AS product_name,
            brands,
            categories,
            categories_tags,
            nutriscore_score,
            nutriscore_grade,
            array_to_string(normalized_ingredients, ', ') AS ingredients_text_normalized,
            array_length(normalized_ingredients) AS ingredients_count
        FROM normalized_data
        """,
        duckdb_conn_id="duckdb_default",
    )

    end = EmptyOperator(task_id="end")

    start >> create_schema >> extract_data >> load_data >> move_raw_table_to_off >> [
        create_nutritions_table,
        create_product_covers_table,
        create_products_table,
    ] >> end