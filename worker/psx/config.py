from __future__ import annotations

import os
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
DATA_DIR = Path(os.environ.get("PSX_DATA_DIR", Path.home() / "psx-data"))
RAW_SUMMARY_DIR = DATA_DIR / "raw" / "mkt_summary"
PSX_BASE = "https://dps.psx.com.pk"
SOURCE_SUMMARY = "PSX Data Portal - daily market summary (dps.psx.com.pk/download/mkt_summary)"
SOURCE_INDEX = "PSX Data Portal - index timeseries (dps.psx.com.pk/timeseries/eod)"
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET") or os.environ.get("JWT_SECRET", "local-dev-secret-change-me-0123456789abcdef")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
