"""Load step: landing-zone files -> DuckDB `raw` schema.

* Match files are immutable events; the natural key is match_id, so loads are
  de-duplicated on match_id (inside the file and against what is already loaded).
* Hero files are daily snapshots; re-loading a snapshot replaces that day only.
Both are tracked in raw.load_log and run inside one transaction per file.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import duckdb

from . import config

log = logging.getLogger(__name__)

MATCH_COLUMNS: dict[str, str] = {
    "match_id": "BIGINT",
    "match_seq_num": "BIGINT",
    "start_time": "BIGINT",
    "duration": "INTEGER",
    "radiant_win": "BOOLEAN",
    "avg_rank_tier": "DOUBLE",
    "num_rank_tier": "INTEGER",
    "game_mode": "INTEGER",
    "lobby_type": "INTEGER",
    "cluster": "INTEGER",
    "radiant_team": "INTEGER[]",
    "dire_team": "INTEGER[]",
    "ingested_at": "TIMESTAMP",
}

HERO_COLUMNS: dict[str, str] = {
    "id": "INTEGER",
    "name": "VARCHAR",
    "localized_name": "VARCHAR",
    "primary_attr": "VARCHAR",
    "attack_type": "VARCHAR",
    "roles": "VARCHAR[]",
}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _columns_literal(columns: dict[str, str]) -> str:
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in columns.items()) + "}"


def connect(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    match_cols = ", ".join(f"{k} {v}" for k, v in MATCH_COLUMNS.items())
    con.execute(
        f"CREATE TABLE IF NOT EXISTS raw.public_matches ({match_cols}, _source_file VARCHAR, _loaded_at TIMESTAMP)"
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.heroes_snapshots (
            snapshot_date DATE, id INTEGER, name VARCHAR, localized_name VARCHAR,
            primary_attr VARCHAR, attack_type VARCHAR, roles VARCHAR[],
            _source_file VARCHAR, _loaded_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw.load_log (
            source_file VARCHAR, kind VARCHAR,
            rows_read BIGINT, rows_inserted BIGINT, loaded_at TIMESTAMP
        )
        """
    )


def _key(path: Path, raw_dir: Path | None) -> str:
    base = Path(raw_dir or config.RAW_DIR)
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.name


def load_match_file(
    con: duckdb.DuckDBPyConnection, path: Path | str, raw_dir: Path | None = None
) -> dict | None:
    """Load one NDJSON file. Returns {'read', 'inserted'}, or None if already loaded."""
    path = Path(path)
    key = _key(path, raw_dir)
    if con.execute("SELECT count(*) FROM raw.load_log WHERE source_file = ?", [key]).fetchone()[0]:
        return None

    src = (
        f"read_json({_quote(path.as_posix())}, format='newline_delimited', "
        f"columns={_columns_literal(MATCH_COLUMNS)})"
    )
    cols = ", ".join(f"s.{c}" for c in MATCH_COLUMNS)

    con.execute("BEGIN TRANSACTION")
    try:
        rows_read = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
        before = con.execute("SELECT count(*) FROM raw.public_matches").fetchone()[0]
        con.execute(
            f"""
            INSERT INTO raw.public_matches
            SELECT {cols}, {_quote(key)} AS _source_file, now()::TIMESTAMP AS _loaded_at
            FROM {src} AS s
            WHERE s.match_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM raw.public_matches p WHERE p.match_id = s.match_id)
            QUALIFY row_number() OVER (PARTITION BY s.match_id ORDER BY s.ingested_at DESC) = 1
            """
        )
        inserted = con.execute("SELECT count(*) FROM raw.public_matches").fetchone()[0] - before
        con.execute(
            "INSERT INTO raw.load_log VALUES (?, 'public_matches', ?, ?, now()::TIMESTAMP)",
            [key, rows_read, inserted],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log.info("Loaded %s: read=%d inserted=%d", key, rows_read, inserted)
    return {"read": rows_read, "inserted": inserted}


def load_heroes_file(
    con: duckdb.DuckDBPyConnection, path: Path | str, raw_dir: Path | None = None
) -> int:
    """Replace the snapshot of the day contained in the file name (heroes_YYYY-MM-DD.json)."""
    path = Path(path)
    match = re.search(r"heroes_(\d{4}-\d{2}-\d{2})\.json$", path.name)
    if not match:
        raise ValueError(f"Unexpected hero file name: {path.name}")
    snapshot = match.group(1)
    key = _key(path, raw_dir)
    src = (
        f"read_json({_quote(path.as_posix())}, format='array', "
        f"columns={_columns_literal(HERO_COLUMNS)})"
    )

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM raw.heroes_snapshots WHERE snapshot_date = ?", [snapshot])
        con.execute("DELETE FROM raw.load_log WHERE source_file = ?", [key])
        con.execute(
            f"""
            INSERT INTO raw.heroes_snapshots
            SELECT CAST({_quote(snapshot)} AS DATE), id, name, localized_name, primary_attr,
                   attack_type, roles, {_quote(key)}, now()::TIMESTAMP
            FROM {src}
            """
        )
        rows = con.execute(
            "SELECT count(*) FROM raw.heroes_snapshots WHERE snapshot_date = ?", [snapshot]
        ).fetchone()[0]
        con.execute("INSERT INTO raw.load_log VALUES (?, 'heroes', ?, ?, now()::TIMESTAMP)", [key, rows, rows])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log.info("Loaded %d heroes (snapshot %s)", rows, snapshot)
    return rows


def load_all(con: duckdb.DuckDBPyConnection, raw_dir: Path | None = None) -> dict:
    """Load every file in the landing zone that has not been loaded yet."""
    base = Path(raw_dir or config.RAW_DIR)
    summary = {"hero_files": 0, "match_files": 0, "matches_inserted": 0}
    for path in sorted((base / "heroes").glob("heroes_*.json")):
        load_heroes_file(con, path, base)
        summary["hero_files"] += 1
    for path in sorted((base / "public_matches").glob("dt=*/matches_*.ndjson")):
        result = load_match_file(con, path, base)
        if result is not None:
            summary["match_files"] += 1
            summary["matches_inserted"] += result["inserted"]
    return summary
