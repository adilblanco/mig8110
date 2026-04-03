import click

command = click.option(
    "--command",
    required=True,
    type=click.Choice([
        "extract_data",
        "filter_data",
        "validate_data",
        "transform_data",
        "load_data",
        "fetch_delta_index",
        "extract_delta",
        "filter_delta",
        "load_delta",
        "transform_delta",
        "merge_data",
    ]),
    help="Command to execute",
)

url = click.option(
    "--url",
    type=str,
    default=None,
    help="URL to fetch data from",
)

input_file_key = click.option(
    "--input_file_key",
    type=str,
    default=None,
    help="Input file key in S3",
)

output_file_key = click.option(
    "--output_file_key",
    type=str,
    default=None,
    help="Output file key in S3",
)

products_output_file_key = click.option(
    "--products_output_file_key",
    type=str,
    default=None,
    help="Output file key in S3 for transformed products parquet",
)

ingredients_output_file_key = click.option(
    "--ingredients_output_file_key",
    type=str,
    default=None,
    help="Output file key in S3 for transformed ingredients parquet",
)

product_ingredients_output_file_key = click.option(
    "--product_ingredients_output_file_key",
    type=str,
    default=None,
    help="Output file key in S3 for transformed product_ingredients parquet",
)

table_name = click.option(
    "--table_name",
    type=str,
    default=None,
    help="MotherDuck / DuckDB table name to load data into",
)

schema_name = click.option(
    "--schema_name",
    type=str,
    default=None,
    help="DuckDB schema name",
)

filename = click.option(
    "--filename",
    type=str,
    default=None,
    help="Delta filename to process (e.g. openfoodfacts_products_xxx.json.gz)",
)

base_url = click.option(
    "--base_url",
    type=str,
    default=None,
    help="Base URL of the delta directory (e.g. https://static.openfoodfacts.org/data/delta/)",
)

invalid_file_key = click.option(
    "--invalid_file_key",
    type=str,
    default=None,
    help="Output file key in S3 for invalid records",
)

country = click.option(
    "--country",
    type=str,
    default="canada",
    help="Country to filter delta records on (substring match against countries_tags, default: canada)",
)

columns = click.option(
    "--columns",
    type=str,
    default=None,
    help="Comma-separated list of columns to keep (e.g. code,product_name,brands)",
)