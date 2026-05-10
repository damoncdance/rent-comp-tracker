"""Shared utility functions for the dashboard package."""
from __future__ import annotations

import html as html_mod
import json
import re
from datetime import date, datetime


def fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return iso


def fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return iso[:10] if iso else ""


_VACANT_THRESHOLD_DAYS = 7


def is_vacant(raw_date: str, today: date) -> bool:
    """Return True if the unit's availability date is within 7 days of today."""
    d = parse_avail_date(raw_date)
    if d is None:
        return False
    return (d - today).days <= _VACANT_THRESHOLD_DAYS


def parse_avail_date(raw: str) -> date | None:
    """Parse an availability date string into a date object.

    Handles multiple formats: 'M/D/YYYY', 'YYYY-MM-DD', ISO 8601.
    Returns None if unparseable or empty.
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except Exception:
        return None


_SAFE_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*$')


def safe_slug(slug: str) -> str:
    """Validate and return a slug safe for filesystem paths."""
    if not slug or not _SAFE_SLUG_RE.match(slug):
        raise ValueError(f"Unsafe slug rejected: {slug!r}")
    return slug


def e(s) -> str:
    """HTML-escape a value for safe interpolation."""
    if s is None:
        return ""
    return html_mod.escape(str(s), quote=True)


def json_safe(data) -> str:
    """Serialize data to JSON safe for embedding inside <script> tags."""
    raw = json.dumps(data, ensure_ascii=True)
    raw = raw.replace("</", r"<\/")
    raw = raw.replace("<!--", r"<\!--")
    return raw
