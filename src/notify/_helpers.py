"""Shared helpers for the notify package."""
from __future__ import annotations

import html as html_mod
import os
from datetime import datetime

from src.config import DASHBOARD_DIR


def fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return iso


def e(s) -> str:
    if s is None:
        return ""
    return html_mod.escape(str(s), quote=True)


def missing_config() -> list[str]:
    required = ["RESEND_API_KEY", "NOTIFY_FROM", "NOTIFY_TO"]
    return [k for k in required if not os.environ.get(k)]


def dashboard_url() -> str:
    explicit = os.environ.get("DASHBOARD_URL", "").strip()
    if explicit:
        return explicit
    return (DASHBOARD_DIR / "index.html").as_uri()
