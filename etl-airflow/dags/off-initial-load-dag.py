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

# S3 keys
RAW_FILE_KEY = f"{DAG_ID}/data.parquet"
FILTERED_FILE_KEY = f"{DAG_ID}/data_filtered.parquet"
VALID_FILE_KEY = f"{DAG_ID}/data_valid.parquet"
INVALID_FILE_KEY = f"{DAG_ID}/data_invalid.parquet"
TRANSFORMED_FILE_KEY = f"{DAG_ID}/data_transformed.parquet"

FILTER_COLUMNS = ",".join([
    "code", "brands", "product_name", "product_quantity", "product_quantity_unit",
    "quantity", "serving_quantity", "serving_size", "categories_tags", "countries_tags",
    "ecoscore_score", "ecoscore_grade", "images",
    "ingredients_analysis_tags", "ingredients_percent_analysis",
    "ingredients_from_palm_oil_n", "ingredients_n",
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
        sql="""
            CREATE OR REPLACE TABLE off.staging.products AS
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
            FROM off.staging.source_transformed
            WHERE code IS NOT NULL;
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
    load_silver >> load_rejected
    [create_products_table, load_rejected] >> end