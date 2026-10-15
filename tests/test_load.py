import json

import duckdb
import pytest

from conftest import match
from dota_pipeline import load


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    load.init_schema(c)
    yield c
    c.close()


def write_ndjson(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    full = [{**m, "radiant_team": m["radiant_team"], "ingested_at": "2026-10-15 10:00:00"} for m in rows]
    path.write_text("\n".join(json.dumps(r) for r in full) + "\n")
    return path


def test_loads_lists_and_types(con, tmp_path):
    f = write_ndjson(tmp_path / "public_matches/dt=2026-10-15/matches_a.ndjson", [match(1), match(2)])
    assert load.load_match_file(con, f, tmp_path) == {"read": 2, "inserted": 2}
    row = con.execute("SELECT radiant_team, radiant_win, avg_rank_tier FROM raw.public_matches WHERE match_id = 1").fetchone()
    assert row == ([1, 2, 3, 4, 5], True, 55.0)


def test_same_file_is_loaded_once(con, tmp_path):
    f = write_ndjson(tmp_path / "public_matches/dt=2026-10-15/matches_a.ndjson", [match(1)])
    assert load.load_match_file(con, f, tmp_path) is not None
    assert load.load_match_file(con, f, tmp_path) is None


def test_overlapping_files_are_deduplicated_on_match_id(con, tmp_path):
    a = write_ndjson(tmp_path / "public_matches/dt=2026-10-15/matches_a.ndjson", [match(1), match(2)])
    b = write_ndjson(tmp_path / "public_matches/dt=2026-10-16/matches_b.ndjson", [match(2), match(3), match(3)])
    load.load_match_file(con, a, tmp_path)
    result = load.load_match_file(con, b, tmp_path)
    assert result == {"read": 3, "inserted": 1}  # only match 3 is new
    assert con.execute("SELECT count(*) FROM raw.public_matches").fetchone()[0] == 3


def test_missing_optional_fields_become_null(con, tmp_path):
    rec = match(1)
    del rec["avg_rank_tier"], rec["cluster"]
    f = write_ndjson(tmp_path / "public_matches/dt=2026-10-15/matches_a.ndjson", [rec])
    load.load_match_file(con, f, tmp_path)
    assert con.execute("SELECT avg_rank_tier, cluster FROM raw.public_matches").fetchone() == (None, None)


def test_hero_snapshot_reload_replaces_same_day(con, tmp_path):
    path = tmp_path / "heroes" / "heroes_2026-10-15.json"
    path.parent.mkdir(parents=True)
    heroes = [{"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage",
               "primary_attr": "agi", "attack_type": "Melee", "roles": ["Carry"]}]
    path.write_text(json.dumps(heroes))
    load.load_heroes_file(con, path, tmp_path)
    load.load_heroes_file(con, path, tmp_path)
    assert con.execute("SELECT count(*) FROM raw.heroes_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT roles FROM raw.heroes_snapshots").fetchone()[0] == ["Carry"]
