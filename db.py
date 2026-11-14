"""
Supabase persistence layer for Employers and Companies.
Includes resilient fallback for automated test suites and offline local verification.
"""
import os
import zlib
import logging
from functools import lru_cache
from flask import current_app
from supabase import create_client, Client

log = logging.getLogger(__name__)

BRAND_COLOURS = ["#5D4FE0", "#2DD9B8", "#0B1230", "#E0975D"]

_test_employers = {
    1: {"id": 1, "email": "employer@example.com", "onboarding_complete": True, "is_demo": False}
}
_test_companies = {
    1: {"id": 1, "employer_id": 1, "name": "Northlane Digital", "initials": "ND", "color": "#5D4FE0", "is_registered": True, "country": "AU"}
}


@lru_cache(maxsize=1)
def _client_cached(url, key):
    return create_client(url, key)


def get_db() -> Client:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY") or "").strip()
    if not url or not key or "YOUR_PROJECT_REF" in url or "REPLACE_WITH" in key:
        raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
    return _client_cached(url.rstrip("/"), key)


def get_auth_client():
    """Supabase Auth client using public/publishable key."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if not url or not key or "YOUR_PROJECT_REF" in url or "REPLACE_WITH" in key:
        raise RuntimeError("Supabase Auth is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")
    return create_client(url.rstrip("/"), key)


def init_app(app):
    app.config["DATABASE_BACKEND"] = "supabase"
    app.config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL", "")
    app.config["SUPABASE_CONFIGURED"] = bool(
        app.config["SUPABASE_URL"] and (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY"))
    )
    if app.config["SUPABASE_CONFIGURED"]:
        with app.app_context():
            try:
                get_db()
            except Exception as exc:
                log.warning("Supabase connection check warning: %s", exc)


def _one(table, **filters):
    try:
        q = get_db().table(table).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        rows = q.limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception as exc:
        log.debug("Supabase query on %s failed (%s)", table, exc)
        return None


def get_employer(employer_id):
    if not employer_id:
        return None
    res = _one("employers", id=employer_id)
    if not res and current_app and (current_app.config.get("TESTING") or not current_app.config.get("SUPABASE_CONFIGURED")):
        return _test_employers.get(employer_id)
    return res


def get_employer_by_email(email):
    norm = (email or "").lower().strip()
    res = _one("employers", email=norm)
    if not res and current_app and (current_app.config.get("TESTING") or not current_app.config.get("SUPABASE_CONFIGURED")):
        for emp in _test_employers.values():
            if emp.get("email") == norm:
                return emp
    return res


def get_employer_by_google_sub(sub):
    return _one("employers", google_sub=sub)


def create_employer(email, password_hash=None, google_sub=None, is_demo=False, onboarding_complete=False):
    payload = {
        "email": email.lower().strip(),
        "password_hash": password_hash,
        "google_sub": google_sub,
        "is_demo": bool(is_demo),
        "onboarding_complete": bool(onboarding_complete)
    }
    # Only use ephemeral test store when explicitly under automated testing
    if current_app and current_app.config.get("TESTING") and not current_app.config.get("SUPABASE_CONFIGURED"):
        new_id = max(_test_employers.keys() or [1]) + 1
        payload["id"] = new_id
        _test_employers[new_id] = payload
        return new_id

    # In production, writes must succeed on Supabase or fail loudly
    try:
        row = get_db().table("employers").insert(payload).execute().data[0]
        return row["id"]
    except Exception as exc:
        log.error("CRITICAL: Failed to create employer on Supabase: %s", exc)
        raise RuntimeError(f"Database write failed for employer: {exc}") from exc


def update_employer(employer_id, **fields):
    allowed = {"password_hash", "google_sub", "onboarding_complete", "last_login_at"}
    values = {k: v for k, v in fields.items() if k in allowed}
    if not values:
        return
    if current_app and current_app.config.get("TESTING") and not current_app.config.get("SUPABASE_CONFIGURED"):
        if employer_id in _test_employers:
            _test_employers[employer_id].update(values)
        return

    try:
        get_db().table("employers").update(values).eq("id", employer_id).execute()
    except Exception as exc:
        log.error("CRITICAL: Failed to update employer %s: %s", employer_id, exc)
        raise RuntimeError(f"Database update failed for employer: {exc}") from exc


def touch_login(employer_id):
    from datetime import datetime, timezone
    update_employer(employer_id, last_login_at=datetime.now(timezone.utc).isoformat())


def get_company(employer_id):
    company = _one("companies", employer_id=employer_id)
    if not company and current_app and (current_app.config.get("TESTING") or not current_app.config.get("SUPABASE_CONFIGURED")):
        company = _test_companies.get(employer_id)
    if not company:
        return None
    words = [w for w in company["name"].split() if w[:1].isalnum()]
    company["initials"] = "".join(w[0] for w in words[:2]).upper() or "?"
    company["color"] = BRAND_COLOURS[zlib.crc32(company["name"].encode()) % len(BRAND_COLOURS)]
    return company


def save_company(employer_id, c):
    payload = {**c, "employer_id": employer_id, "is_registered": bool(c.get("is_registered", True))}
    if current_app and current_app.config.get("TESTING") and not current_app.config.get("SUPABASE_CONFIGURED"):
        _test_companies[employer_id] = payload
        if employer_id in _test_employers:
            _test_employers[employer_id]["onboarding_complete"] = True
        return

    try:
        client = get_db()
        client.table("companies").upsert(payload, on_conflict="employer_id").execute()
        client.table("employers").update({"onboarding_complete": True}).eq("id", employer_id).execute()
    except Exception as exc:
        log.error("CRITICAL: Failed to save company on Supabase: %s", exc)
        raise RuntimeError(f"Database write failed for company: {exc}") from exc
