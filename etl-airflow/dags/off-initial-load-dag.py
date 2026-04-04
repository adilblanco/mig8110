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

DATABASE_NAME = "off"
RAW_SCHEMA = "raw"
STAGING_SCHEMA = "staging"

RAW_TABLE_NAME = "canada_products"
REJECTED_TABLE_NAME = "source_rejected"

PRODUCTS_TABLE_NAME = "products"
INGREDIENTS_TABLE_NAME = "ingredients"
PRODUCT_INGREDIENTS_TABLE_NAME = "product_ingredients"

RAW_FILE_KEY = f"{DAG_ID}/data.parquet"
FILTERED_FILE_KEY = f"{DAG_ID}/data_filtered.parquet"
VALID_FILE_KEY = f"{DAG_ID}/data_valid.parquet"
INVALID_FILE_KEY = f"{DAG_ID}/data_invalid.parquet"

PRODUCTS_FILE_KEY = f"{DAG_ID}/products.parquet"
INGREDIENTS_FILE_KEY = f"{DAG_ID}/ingredients.parquet"
PRODUCT_INGREDIENTS_FILE_KEY = f"{DAG_ID}/product_ingredients.parquet"

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
    "ingredients_n",
    "ingredients",
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
    env_vars={
        **s3_env_vars,
        "OFF_INGREDIENTS_TAXONOMY_PATH": "/app/resources/ingredients.txt",
    },
    arguments=[
        "--command", "transform_data",
        "--input_file_key", VALID_FILE_KEY,
        "--products_output_file_key", PRODUCTS_FILE_KEY,
        "--ingredients_output_file_key", INGREDIENTS_FILE_KEY,
        "--product_ingredients_output_file_key", PRODUCT_INGREDIENTS_FILE_KEY,
    ],
)

    load_products = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-products",
        name="load-products",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", PRODUCTS_FILE_KEY,
            "--table_name", PRODUCTS_TABLE_NAME,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    load_ingredients = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-ingredients",
        name="load-ingredients",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", INGREDIENTS_FILE_KEY,
            "--table_name", INGREDIENTS_TABLE_NAME,
            "--schema_name", f"{DATABASE_NAME}.{STAGING_SCHEMA}",
        ],
    )

    load_product_ingredients = CustomKubernetesPodOperator(
        dag=dag,
        task_id="load-product-ingredients",
        name="load-product-ingredients",
        image=IMAGE,
        env_vars={**s3_env_vars, **duckdb_env_vars},
        arguments=[
            "--command", "load_data",
            "--input_file_key", PRODUCT_INGREDIENTS_FILE_KEY,
            "--table_name", PRODUCT_INGREDIENTS_TABLE_NAME,
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

    start >> create_schemas >> extract_data >> filter_data >> load_bronze >> validate_data

    validate_data >> transform_data
    validate_data >> load_rejected

    transform_data >> load_products
    transform_data >> load_ingredients
    transform_data >> load_product_ingredients

    [load_products, load_ingredients, load_product_ingredients, load_rejected] >> end