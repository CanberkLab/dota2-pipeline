"""Runs the real ingest code against the local mock API, then loads into DuckDB."""
import duckdb
import pytest

from dota_pipeline import ingest, load
from dota_pipeline.mock_api import start_mock_server


@pytest.fixture()
def api():
    server, url = start_mock_server(size=450)
    yield url
    server.shutdown()


def test_full_extract_load_and_incremental_second_run(api, tmp_path):
    client = ingest.OpenDotaClient(base_url=api, min_interval=0)
    ingest.ingest_heroes(client, raw_dir=tmp_path)
    first = ingest.ingest_public_matches(client, raw_dir=tmp_path, max_pages=10)
    assert first["new_matches"] == 450 and first["pages"] == 6  # 5 data pages + the empty page that ends the walk

    con = duckdb.connect(":memory:")
    load.init_schema(con)
    assert load.load_all(con, tmp_path)["matches_inserted"] == 450

    # Nothing new on the API: no extra file, no extra rows, only one page requested.
    again = ingest.ingest_public_matches(client, raw_dir=tmp_path, max_pages=10)
    assert again["file"] is None and again["pages"] == 1

    # A bigger universe = 120 newer matches appear; only those are fetched.
    server, url = start_mock_server(size=570)
    try:
        client2 = ingest.OpenDotaClient(base_url=url, min_interval=0)
        third = ingest.ingest_public_matches(client2, raw_dir=tmp_path, max_pages=10)
    finally:
        server.shutdown()
    assert third["new_matches"] == 120
    # Re-running the loader is safe and adds exactly the new matches.
    assert load.load_all(con, tmp_path)["matches_inserted"] == 120
    assert con.execute("SELECT count(*) FROM raw.public_matches").fetchone()[0] == 570
