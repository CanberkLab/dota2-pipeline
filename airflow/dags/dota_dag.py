"""Hourly Airflow DAG: extract -> load -> dbt build.

/publicMatches only exposes RECENT matches, so there is nothing to backfill:
catchup is off and the schedule decides how much of the ladder you capture.
All tasks are idempotent (watermark + de-duplication), so retries are safe.

Setup (local):
    pip install -e ".[airflow]"
    export PROJECT_ROOT=$(pwd)
    export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/airflow/dags
    airflow standalone
"""
from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.operators.bash import BashOperator

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.getcwd())
PAGES = int(os.environ.get("DOTA_PAGES", "20"))  # 100 matches per page


@dag(
    dag_id="dota_public_matches",
    schedule="@hourly",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,  # DuckDB allows a single writer
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["dota2", "opendota"],
)
def dota_public_matches():
    @task
    def extract() -> dict:
        from dota_pipeline import ingest

        client = ingest.OpenDotaClient()
        ingest.ingest_heroes(client)
        return ingest.ingest_public_matches(client, max_pages=PAGES)

    @task
    def load_raw(extract_summary: dict) -> dict:
        from dota_pipeline import load

        con = load.connect()
        try:
            load.init_schema(con)
            return load.load_all(con)
        finally:
            con.close()

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f'cd "{PROJECT_ROOT}/dbt_project" && dbt build --profiles-dir .',
        env={"DUCKDB_PATH": os.environ.get("DUCKDB_PATH", f"{PROJECT_ROOT}/data/warehouse/dota.duckdb")},
        append_env=True,
    )

    load_raw(extract()) >> dbt_build


dota_public_matches()
