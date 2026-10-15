"""Central configuration. Everything can be overridden with environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.getenv("DUCKDB_PATH", DATA_DIR / "warehouse" / "dota.duckdb"))
DBT_DIR = ROOT / "dbt_project"

BASE_URL = os.getenv("OPENDOTA_BASE_URL", "https://api.opendota.com/api")
API_KEY = os.getenv("OPENDOTA_API_KEY") or None  # optional, raises rate limits
# The free tier allows roughly 60 requests/minute; stay a little under 1 request/second.
MIN_INTERVAL = float(os.getenv("OPENDOTA_MIN_INTERVAL", "1.1"))
