from __future__ import annotations

import os
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
DATA_DIR = Path(os.environ.get("PSX_DATA_DIR", Path.home() / "psx-data"))
RAW_SUMMARY_DIR = DATA_DIR / "raw" / "mkt_summary"
PSX_BASE = "https://dps.psx.com.pk"
SOURCE_SUMMARY = "PSX Data Portal - daily market summary (dps.psx.com.pk/download/mkt_summary)"
SOURCE_INDEX = "PSX Data Portal - index timeseries (dps.psx.com.pk/timeseries/eod)"


def _env(name: str, valid) -> str:
    """Return an env value only if it looks real; placeholders (e.g. the variable's own name) count as unset."""
    v = os.environ.get(name, "").strip()
    return v if v and v != name and valid(v) else ""


SUPABASE_JWT_SECRET = _env("SUPABASE_JWT_SECRET", lambda v: len(v) >= 32)
SUPABASE_URL = _env("SUPABASE_URL", lambda v: v.startswith("https://"))
JWT_SECRET = SUPABASE_JWT_SECRET or _env("JWT_SECRET", lambda v: len(v) >= 32) or "local-dev-secret-change-me-0123456789abcdef"
SUPABASE_ANON_KEY = _env("SUPABASE_ANON_KEY", lambda v: len(v) >= 20)
AUTH_MODE = "supabase" if SUPABASE_JWT_SECRET else "local"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
