"""Extract step: OpenDota API -> files in the raw landing zone.

Landing zone layout (immutable files, Hive-style partitions):

    data/raw/heroes/heroes_YYYY-MM-DD.json
    data/raw/public_matches/dt=YYYY-MM-DD/matches_<UTC timestamp>.ndjson
    data/raw/_state/public_matches.json          <- high-water mark (max match_id)
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from . import config

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Raised when the API keeps failing after all retries."""


class OpenDotaClient:
    """Small HTTP client: client-side throttling, retries with backoff, 429 handling."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        min_interval: float | None = None,
        session: Any = None,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.API_KEY
        self.min_interval = config.MIN_INTERVAL if min_interval is None else min_interval
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self.min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _backoff(self, attempt: int, retry_after: float | None = None) -> None:
        delay = retry_after if retry_after is not None else min(2**attempt, 60)
        log.warning("Retrying in %.1fs (attempt %d/%d)", delay, attempt, self.max_retries)
        self._sleep(delay)

    def get(self, path: str, params: dict | None = None) -> Any:
        params = dict(params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                last_error = exc
                self._backoff(attempt)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = ApiError(f"HTTP {resp.status_code} from {path}")
                header = resp.headers.get("Retry-After", "")
                self._backoff(attempt, float(header) if header.replace(".", "", 1).isdigit() else None)
                continue
            if resp.status_code >= 400:
                raise ApiError(f"HTTP {resp.status_code} from {path}")
            return resp.json()

        raise ApiError(f"Giving up on {path} after {self.max_retries} attempts") from last_error


# ----------------------------------------------------------------------------- helpers

def _hero_list(value: Any) -> list[int] | None:
    """The API has returned team hero ids both as a list and as 'a,b,c' strings."""
    if value is None:
        return None
    if isinstance(value, str):
        value = [v for v in value.split(",") if v.strip()]
    return [int(v) for v in value]


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


def normalize_match(rec: dict, ingested_at: str) -> dict | None:
    """Project one API record onto a stable shape. Returns None if unusable."""
    if rec.get("match_id") is None:
        return None
    return {
        "match_id": int(rec["match_id"]),
        "match_seq_num": _int(rec.get("match_seq_num")),
        "start_time": _int(rec.get("start_time")),
        "duration": _int(rec.get("duration")),
        "radiant_win": None if rec.get("radiant_win") is None else bool(rec["radiant_win"]),
        "avg_rank_tier": None if rec.get("avg_rank_tier") is None else float(rec["avg_rank_tier"]),
        "num_rank_tier": _int(rec.get("num_rank_tier")),
        "game_mode": _int(rec.get("game_mode")),
        "lobby_type": _int(rec.get("lobby_type")),
        "cluster": _int(rec.get("cluster")),
        "radiant_team": _hero_list(rec.get("radiant_team")),
        "dire_team": _hero_list(rec.get("dire_team")),
        "ingested_at": ingested_at,
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _unique_path(path: Path) -> Path:
    """Landing-zone files are immutable: never overwrite an existing file."""
    candidate, n = path, 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- state

def state_path(raw_dir: Path | None = None) -> Path:
    return Path(raw_dir or config.RAW_DIR) / "_state" / "public_matches.json"


def read_watermark(raw_dir: Path | None = None) -> int | None:
    path = state_path(raw_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("max_match_id")


def write_watermark(match_id: int, raw_dir: Path | None = None) -> None:
    payload = {"max_match_id": match_id, "updated_at": _utcnow().strftime("%Y-%m-%d %H:%M:%S")}
    _atomic_write(state_path(raw_dir), json.dumps(payload))


# ----------------------------------------------------------------------------- heroes

def ingest_heroes(client: OpenDotaClient, raw_dir: Path | None = None, today: datetime | None = None) -> Path:
    """Snapshot of the hero list. One file per day; re-running the same day replaces it."""
    heroes = client.get("/heroes")
    if not isinstance(heroes, list) or not heroes:
        raise ApiError("/heroes returned no data")
    day = (today or _utcnow()).strftime("%Y-%m-%d")
    path = Path(raw_dir or config.RAW_DIR) / "heroes" / f"heroes_{day}.json"
    _atomic_write(path, json.dumps(heroes))
    log.info("Saved %d heroes to %s", len(heroes), path.name)
    return path


# ----------------------------------------------------------------------------- matches

def fetch_public_matches(
    client: OpenDotaClient,
    max_pages: int = 20,
    min_rank: int | None = None,
    watermark: int | None = None,
) -> tuple[list[dict], int]:
    """Page backwards from the newest matches until the watermark (or max_pages).

    /publicMatches returns up to 100 recent matches per call; older pages are
    requested with less_than_match_id=<lowest id seen so far>.
    """
    collected: dict[int, dict] = {}
    cursor: int | None = None
    pages = 0

    while pages < max_pages:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["less_than_match_id"] = cursor
        if min_rank is not None:
            params["min_rank"] = min_rank

        batch = client.get("/publicMatches", params)
        pages += 1
        if not batch:
            break

        new = [m for m in batch if watermark is None or int(m["match_id"]) > watermark]
        for m in new:
            collected[int(m["match_id"])] = m
        cursor = min(int(m["match_id"]) for m in batch)
        if len(new) < len(batch):  # we reached matches that were already ingested
            break

    return list(collected.values()), pages


def ingest_public_matches(
    client: OpenDotaClient,
    raw_dir: Path | None = None,
    max_pages: int = 20,
    min_rank: int | None = None,
    now: datetime | None = None,
) -> dict:
    raw_dir = Path(raw_dir or config.RAW_DIR)
    now = now or _utcnow()
    watermark = read_watermark(raw_dir)

    records, pages = fetch_public_matches(client, max_pages, min_rank, watermark)
    ingested_at = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = [r for r in (normalize_match(rec, ingested_at) for rec in records) if r is not None]
    summary = {"pages": pages, "new_matches": len(rows), "file": None, "watermark": watermark}

    if not rows:
        log.info("No new matches (watermark=%s)", watermark)
        return summary

    path = _unique_path(
        raw_dir / "public_matches" / f"dt={now:%Y-%m-%d}" / f"matches_{now:%Y%m%dT%H%M%S%f}Z.ndjson"
    )
    _atomic_write(path, "\n".join(json.dumps(r) for r in rows) + "\n")
    # The watermark moves only after the file is safely on disk.
    summary["watermark"] = max(r["match_id"] for r in rows)
    write_watermark(summary["watermark"], raw_dir)
    summary["file"] = str(path)
    log.info("Fetched %d new matches in %d pages -> %s", len(rows), pages, path.name)
    return summary
