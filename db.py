"""Supabase-only persistence layer. No local SQLite database is created."""
import os
import zlib
from functools import lru_cache
from flask import current_app
from supabase import create_client, Client

BRAND_COLOURS = ["#5D4FE0", "#2DD9B8", "#0B1230", "#E0975D"]

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
    """Supabase Auth client using the public/publishable key (never the service key)."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if not url or not key or "YOUR_PROJECT_REF" in url or "REPLACE_WITH" in key:
        raise RuntimeError("Supabase Auth is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")
    return create_client(url.rstrip("/"), key)

def init_app(app):
    # Fail fast rather than silently falling back to local storage.
    app.config["DATABASE_BACKEND"] = "supabase"
    app.config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL", "")
    app.config["SUPABASE_CONFIGURED"] = bool(app.config["SUPABASE_URL"] and (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")))
    if app.config["SUPABASE_CONFIGURED"]:
        with app.app_context():
            get_db()

def _one(table, **filters):
    q = get_db().table(table).select("*")
    for k, v in filters.items(): q = q.eq(k, v)
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None

def get_employer(employer_id):
    return _one("employers", id=employer_id) if employer_id else None

def get_employer_by_email(email): return _one("employers", email=(email or "").lower())
def get_employer_by_google_sub(sub): return _one("employers", google_sub=sub)

def create_employer(email, password_hash=None, google_sub=None, is_demo=False, onboarding_complete=False):
    row = get_db().table("employers").insert({"email": email.lower(), "password_hash": password_hash, "google_sub": google_sub, "is_demo": bool(is_demo), "onboarding_complete": bool(onboarding_complete)}).execute().data[0]
    return row["id"]

def update_employer(employer_id, **fields):
    allowed = {"password_hash", "google_sub", "onboarding_complete", "last_login_at"}
    values = {k: v for k, v in fields.items() if k in allowed}
    if values: get_db().table("employers").update(values).eq("id", employer_id).execute()

def touch_login(employer_id):
    from datetime import datetime, timezone
    get_db().table("employers").update({"last_login_at": datetime.now(timezone.utc).isoformat()}).eq("id", employer_id).execute()

def get_company(employer_id):
    company = _one("companies", employer_id=employer_id)
    if not company: return None
    words = [w for w in company["name"].split() if w[:1].isalnum()]
    company["initials"] = "".join(w[0] for w in words[:2]).upper() or "?"
    company["color"] = BRAND_COLOURS[zlib.crc32(company["name"].encode()) % len(BRAND_COLOURS)]
    return company

def save_company(employer_id, c):
    client = get_db()
    payload = {**c, "employer_id": employer_id, "is_registered": bool(c.get("is_registered", True))}
    client.table("companies").upsert(payload, on_conflict="employer_id").execute()
    client.table("employers").update({"onboarding_complete": True}).eq("id", employer_id).execute()
