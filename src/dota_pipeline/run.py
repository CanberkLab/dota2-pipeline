"""CLI entrypoint: extract -> load -> transform (dbt build).

Examples:
    python -m dota_pipeline.run --pages 20                 # real OpenDota API
    python -m dota_pipeline.run --mock --mock-size 5000    # offline demo
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

from . import config, ingest, load

log = logging.getLogger("dota_pipeline")


_DBT_SNIPPET = (
    "import sys; from dbt.cli.main import dbtRunner; "
    "sys.exit(0 if dbtRunner().invoke(sys.argv[1:]).success else 1)"
)


def run_dbt(*args: str) -> None:
    """Run dbt through its official Python API, using THIS interpreter.

    No `dbt` executable on PATH is needed (and the project path may contain spaces,
    which breaks venv console scripts).
    """
    command = list(args) or ["build"]
    env = {**os.environ, "DUCKDB_PATH": str(config.DB_PATH)}
    log.info("Running dbt %s", " ".join(command))
    subprocess.run(
        [sys.executable, "-c", _DBT_SNIPPET, *command,
         "--project-dir", str(config.DBT_DIR), "--profiles-dir", str(config.DBT_DIR)],
        env=env, check=True,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--pages", type=int, default=20, help="max /publicMatches pages (100 matches each)")
    parser.add_argument("--min-rank", type=int, help="only matches at or above this rank tier (e.g. 50 = Legend)")
    parser.add_argument("--skip-fetch", action="store_true", help="do not call the API, load existing files")
    parser.add_argument("--skip-dbt", action="store_true", help="only extract and load")
    parser.add_argument("--mock", action="store_true", help="use the built-in fake API (offline, synthetic data)")
    parser.add_argument("--mock-size", type=int, default=5000, help="matches in the fake universe")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    server = None
    try:
        if not args.skip_fetch:
            if args.mock:
                from .mock_api import start_mock_server

                server, url = start_mock_server(args.mock_size)
                client = ingest.OpenDotaClient(base_url=url, min_interval=0)
                log.info("Using mock API at %s (synthetic data)", url)
            else:
                client = ingest.OpenDotaClient()
            ingest.ingest_heroes(client)
            ingest.ingest_public_matches(client, max_pages=args.pages, min_rank=args.min_rank)
    finally:
        if server is not None:
            server.shutdown()

    con = load.connect()
    try:
        load.init_schema(con)
        log.info("Load summary: %s", load.load_all(con))
    finally:
        con.close()  # release the file lock before dbt opens the same database

    if not args.skip_dbt:
        run_dbt("build")
    log.info("Done. Database: %s", config.DB_PATH)


if __name__ == "__main__":
    main()
