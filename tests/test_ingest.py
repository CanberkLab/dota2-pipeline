import json
from datetime import datetime, timezone

import pytest
import requests

from conftest import FakeResponse, match
from dota_pipeline import ingest

NOW = datetime(2026, 10, 15, 10, 30, tzinfo=timezone.utc)


def test_team_lists_are_normalised_from_strings_and_lists():
    rec = match(1, radiant_team="1,2,3,4,5", dire_team=[6, 7, 8, 9, 10])
    out = ingest.normalize_match(rec, "2026-10-15 10:00:00")
    assert out["radiant_team"] == [1, 2, 3, 4, 5]
    assert out["dire_team"] == [6, 7, 8, 9, 10]


def test_record_without_match_id_is_dropped():
    assert ingest.normalize_match({"duration": 10}, "x") is None


def test_pagination_walks_backwards_with_less_than_match_id(make_client):
    client = make_client([
        FakeResponse([match(300), match(200)]),
        FakeResponse([match(100)]),
        FakeResponse([]),
    ])
    records, pages = ingest.fetch_public_matches(client, max_pages=10)
    assert sorted(m["match_id"] for m in records) == [100, 200, 300]
    assert pages == 3
    calls = client.session_ref.calls
    assert "less_than_match_id" not in calls[0][1]
    assert calls[1][1]["less_than_match_id"] == 200
    assert calls[2][1]["less_than_match_id"] == 100


def test_stops_at_watermark(make_client):
    client = make_client([FakeResponse([match(500), match(400), match(300)])])
    records, pages = ingest.fetch_public_matches(client, max_pages=10, watermark=400)
    assert [m["match_id"] for m in records] == [500]
    assert pages == 1  # no second request once old matches were seen


def test_max_pages_is_respected(make_client):
    client = make_client([FakeResponse([match(300)]), FakeResponse([match(200)])])
    _, pages = ingest.fetch_public_matches(client, max_pages=2)
    assert pages == 2


def test_retries_on_429_and_honours_retry_after(make_client):
    client = make_client([FakeResponse({}, 429, {"Retry-After": "7"}), FakeResponse([{"id": 1}])])
    assert client.get("/heroes") == [{"id": 1}]
    assert client.sleeps == [7.0]


def test_retries_on_connection_error_then_gives_up(make_client):
    client = make_client([requests.ConnectionError("boom")] * 3, max_retries=3)
    with pytest.raises(ingest.ApiError):
        client.get("/heroes")


def test_client_error_is_not_retried(make_client):
    client = make_client([FakeResponse({}, 404)])
    with pytest.raises(ingest.ApiError):
        client.get("/nope")
    assert len(client.session_ref.calls) == 1


def test_api_key_is_sent_when_configured(make_client):
    client = make_client([FakeResponse([])], api_key="secret")
    client.get("/heroes")
    assert client.session_ref.calls[0][1]["api_key"] == "secret"


def test_ingest_writes_ndjson_and_moves_watermark_only_after_write(make_client, tmp_path):
    client = make_client([FakeResponse([match(20), match(10, radiant_team="1,2,3,4,5")]), FakeResponse([])])
    summary = ingest.ingest_public_matches(client, raw_dir=tmp_path, max_pages=5, now=NOW)

    assert summary["new_matches"] == 2
    assert "dt=2026-10-15" in summary["file"]
    lines = [json.loads(line) for line in open(summary["file"])]
    assert {row["match_id"] for row in lines} == {10, 20}
    assert all(isinstance(row["radiant_team"], list) for row in lines)
    assert ingest.read_watermark(tmp_path) == 20


def test_second_run_without_new_matches_writes_nothing(make_client, tmp_path):
    ingest.write_watermark(20, tmp_path)
    client = make_client([FakeResponse([match(20), match(10)])])
    summary = ingest.ingest_public_matches(client, raw_dir=tmp_path, now=NOW)
    assert summary["file"] is None and summary["new_matches"] == 0
    assert not (tmp_path / "public_matches").exists()


def test_heroes_snapshot_is_one_file_per_day(make_client, tmp_path):
    client = make_client([FakeResponse([{"id": 1, "localized_name": "Anti-Mage"}])] * 2)
    first = ingest.ingest_heroes(client, raw_dir=tmp_path, today=NOW)
    second = ingest.ingest_heroes(client, raw_dir=tmp_path, today=NOW)
    assert first == second and first.name == "heroes_2026-10-15.json"


def test_empty_heroes_response_is_an_error(make_client, tmp_path):
    client = make_client([FakeResponse([])])
    with pytest.raises(ingest.ApiError):
        ingest.ingest_heroes(client, raw_dir=tmp_path)


def test_landing_files_are_never_overwritten(make_client, tmp_path):
    """Two runs in the same instant must produce two files, not one overwritten file."""
    paths = []
    for mid in (10, 20):
        client = make_client([FakeResponse([match(mid)]), FakeResponse([])])
        paths.append(ingest.ingest_public_matches(client, raw_dir=tmp_path, now=NOW)["file"])
        ingest.write_watermark(0, tmp_path)  # reset so both runs see "new" matches
    assert paths[0] != paths[1]
    assert len(list((tmp_path / "public_matches").rglob("*.ndjson"))) == 2
