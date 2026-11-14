"""
Supabase-backed seeker accounts, profiles, resumes, applications and saved jobs.
Includes test-mode and offline resilient fallback for testing.
"""
import json
import logging
from datetime import datetime, timezone
from flask import current_app, has_app_context

from db import get_db

log = logging.getLogger(__name__)

APPLICATION_STATUSES = ["Applied", "Shortlisted", "Interview", "Rejected"]
RESUME_TEMPLATES = [
    {"id": "modern", "name": "Modern", "blurb": "Bold header with an indigo accent."},
    {"id": "classic", "name": "Classic", "blurb": "Traditional serif layout."},
    {"id": "minimal", "name": "Minimal", "blurb": "Clean, spacious and simple."},
]
PLANS = ("free", "premium")
PROFILE_SECTIONS = [
    {"key": "basic", "label": "Basic Information", "weight": 25, "icon": "user-round"},
    {"key": "education", "label": "Education Details", "weight": 20, "icon": "graduation-cap"},
    {"key": "skills", "label": "Skills & Interests", "weight": 25, "icon": "sparkles"},
    {"key": "experience", "label": "Work Experience", "weight": 20, "icon": "briefcase"},
    {"key": "additional", "label": "Additional Details", "weight": 10, "icon": "list-plus"},
]
_JSON_COLS = ("education", "experience", "skills", "interests")

# Test-mode ephemeral stores for testing/offline runs
_test_seekers = {
    1: {"id": 1, "email": "seeker@example.com", "full_name": "Test Seeker", "plan": "free", "is_demo": False}
}
_test_profiles = {
    1: {
        "seeker_id": 1,
        "headline": "Lead Full-Stack Engineer",
        "phone": "0412 345 678",
        "location": "Sydney, NSW",
        "education": [{"qualification": "B.Sc CS", "institution": "UNSW", "year": "2022"}],
        "experience": [{"title": "Software Engineer", "company": "Northlane Digital", "start": "2022", "end": "2024", "description": "Backend services"}],
        "no_experience": False,
        "skills": ["Python", "React", "PostgreSQL", "Cloud"],
        "interests": ["Distributed Systems"],
        "work_rights": "Australian citizen",
        "pref_job_type": "Full-time",
        "pref_work_mode": "Hybrid",
        "pref_location": "Sydney, NSW",
        "linkedin": "https://linkedin.com/in/test",
        "portfolio": "https://example.com"
    }
}
_test_resumes = {}
_test_applications = []
_test_saved_jobs = set()


def _is_test_or_unconfigured():
    try:
        if has_app_context() and current_app:
            return bool(current_app.config.get("TESTING") or not current_app.config.get("SUPABASE_CONFIGURED"))
    except Exception:
        pass
    # If called outside app context during test runs
    import os
    return not bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _one(table, **filters):
    if _is_test_or_unconfigured():
        return None
    try:
        q = get_db().table(table).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        rows = q.limit(1).execute().data or []
        return rows[0] if rows else None
    except Exception as exc:
        log.debug("Supabase query on %s failed: %s", table, exc)
        return None


def get_seeker(seeker_id):
    if not seeker_id:
        return None
    if _is_test_or_unconfigured():
        return _test_seekers.get(seeker_id)
    res = _one("seekers", id=seeker_id)
    return res or _test_seekers.get(seeker_id)


def get_seeker_by_email(email):
    norm = (email or "").lower().strip()
    if _is_test_or_unconfigured():
        for s in _test_seekers.values():
            if s.get("email") == norm:
                return s
        return None
    res = _one("seekers", email=norm)
    if not res:
        for s in _test_seekers.values():
            if s.get("email") == norm:
                return s
    return res


def get_seeker_by_google_sub(sub):
    return _one("seekers", google_sub=sub)


def create_seeker(email, full_name="", password_hash=None, google_sub=None, is_demo=False):
    payload = {
        "email": email.lower().strip(),
        "full_name": full_name.strip(),
        "password_hash": password_hash,
        "google_sub": google_sub,
        "is_demo": bool(is_demo),
        "plan": "free"
    }
    if _is_test_or_unconfigured():
        new_id = max(_test_seekers.keys() or [1]) + 1
        payload["id"] = new_id
        _test_seekers[new_id] = payload
        _test_profiles[new_id] = {"seeker_id": new_id, "headline": "", "phone": "", "location": "",
                                  "education": [], "experience": [], "skills": [], "interests": [], "work_rights": ""}
        return new_id

    try:
        row = get_db().table("seekers").insert(payload).execute().data[0]
        sid = row["id"]
        get_db().table("seeker_profiles").upsert({"seeker_id": sid}, on_conflict="seeker_id").execute()
        return sid
    except Exception as exc:
        log.error("CRITICAL: Failed to create seeker on Supabase: %s", exc)
        raise RuntimeError(f"Database error creating seeker: {exc}") from exc


def update_seeker(seeker_id, **fields):
    allowed = {"password_hash", "google_sub", "full_name", "plan"}
    values = {k: v for k, v in fields.items() if k in allowed}
    if not values:
        return
    if seeker_id in _test_seekers:
        _test_seekers[seeker_id].update(values)
    if not _is_test_or_unconfigured():
        try:
            get_db().table("seekers").update(values).eq("id", seeker_id).execute()
        except Exception:
            pass


def touch_login(seeker_id):
    try:
        get_db().table("seekers").update({"last_login_at": _now()}).eq("id", seeker_id).execute()
    except Exception:
        pass


def seeker_display(row):
    name = (row.get("full_name") or "").strip() or row.get("email", "").split("@")[0]
    parts = [p for p in name.split() if p]
    plan = row.get("plan", "free")
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "full_name": name,
        "first_name": parts[0] if parts else name,
        "initials": ("".join(p[0] for p in parts[:2]) or name[:1]).upper(),
        "plan": plan,
        "is_premium": plan == "premium"
    }


def get_profile(seeker_id):
    row = None
    if _is_test_or_unconfigured():
        row = _test_profiles.get(seeker_id)
    else:
        try:
            row = _one("seeker_profiles", seeker_id=seeker_id)
            if row is None:
                get_db().table("seeker_profiles").upsert({"seeker_id": seeker_id}, on_conflict="seeker_id").execute()
                row = _one("seeker_profiles", seeker_id=seeker_id)
        except Exception as exc:
            log.debug("get_profile db error for %s: %s", seeker_id, exc)
            row = _test_profiles.get(seeker_id)

    p = dict(row or {
        "seeker_id": seeker_id, "headline": "", "phone": "", "location": "",
        "education": [], "experience": [], "skills": [], "interests": [],
        "work_rights": "", "pref_job_type": "", "pref_work_mode": "", "pref_location": ""
    })
    for col in _JSON_COLS:
        val = p.get(col, [])
        if isinstance(val, str):
            try:
                val = json.loads(val or "[]")
            except ValueError:
                val = []
        p[col] = val or []
    p["no_experience"] = bool(p.get("no_experience"))
    return p


def save_profile_fields(seeker_id, **fields):
    allowed = {
        "headline", "phone", "location", "education", "experience", "no_experience",
        "skills", "interests", "pref_job_type", "pref_work_mode", "pref_location",
        "work_rights", "linkedin", "portfolio"
    }
    values = {k: v for k, v in fields.items() if k in allowed}
    for k in _JSON_COLS:
        if k in values and isinstance(values[k], str):
            try:
                values[k] = json.loads(values[k])
            except ValueError:
                values[k] = []
    if "no_experience" in values:
        values["no_experience"] = bool(values["no_experience"])

    if not values:
        return

    values["updated_at"] = _now()
    prof = _test_profiles.setdefault(seeker_id, {
        "seeker_id": seeker_id, "headline": "", "phone": "", "location": "",
        "education": [], "experience": [], "skills": [], "interests": [],
        "work_rights": "", "pref_job_type": "", "pref_work_mode": "", "pref_location": ""
    })
    prof.update(values)
    _test_profiles[seeker_id] = prof

    if not _is_test_or_unconfigured():
        try:
            get_db().table("seeker_profiles").update(values).eq("seeker_id", seeker_id).execute()
        except Exception as exc:
            log.debug("save_profile_fields error: %s", exc)


def profile_completion(seeker, profile):
    done = {
        "basic": bool((seeker.get("full_name") or "").strip() and profile.get("headline") and profile.get("phone") and profile.get("location")),
        "education": bool(profile.get("education")),
        "skills": len(profile.get("skills", [])) >= 3,
        "experience": bool(profile.get("experience")) or profile.get("no_experience"),
        "additional": bool(profile.get("work_rights") and (profile.get("pref_location") or profile.get("pref_job_type") or profile.get("pref_work_mode"))),
    }
    sections = [{**s, "done": done[s["key"]]} for s in PROFILE_SECTIONS]
    return sum(s["weight"] for s in sections if s["done"]), sections


def get_resume(seeker_id):
    if _is_test_or_unconfigured():
        return _test_resumes.get(seeker_id)
    res = _one("seeker_resumes", seeker_id=seeker_id)
    return res or _test_resumes.get(seeker_id)


def save_resume(seeker_id, template, summary):
    payload = {"seeker_id": seeker_id, "template": template, "summary": summary, "updated_at": _now()}
    _test_resumes[seeker_id] = payload
    if not _is_test_or_unconfigured():
        try:
            get_db().table("seeker_resumes").upsert(payload, on_conflict="seeker_id").execute()
        except Exception as exc:
            log.debug("save_resume test store: %s", exc)


def resume_requirements(seeker, profile, resume):
    return [
        {"label": "Professional summary (40+ characters)", "done": bool(resume and len(resume.get("summary", "")) >= 40), "where": "resume"},
        {"label": "Headline & contact details", "done": bool(profile.get("headline") and profile.get("phone") and profile.get("location")), "where": "basic"},
        {"label": "Education or work experience", "done": bool(profile.get("education") or profile.get("experience")), "where": "education"},
        {"label": "At least 3 skills", "done": len(profile.get("skills", [])) >= 3, "where": "skills"},
    ]


def resume_status(seeker, profile, resume):
    if not resume:
        return "Not started"
    return "Completed" if all(r["done"] for r in resume_requirements(seeker, profile, resume)) else "In progress"


def get_applications(seeker_id):
    if _is_test_or_unconfigured():
        return [a for a in _test_applications if a.get("seeker_id") == seeker_id]
    try:
        return (get_db().table("applications").select("*").eq("seeker_id", seeker_id)
                .order("applied_at", desc=True).order("id", desc=True).execute().data or [])
    except Exception:
        return [a for a in _test_applications if a.get("seeker_id") == seeker_id]


def applied_job_ids(seeker_id):
    if _is_test_or_unconfigured():
        return {a["job_id"] for a in _test_applications if a.get("seeker_id") == seeker_id}
    try:
        return {r["job_id"] for r in (get_db().table("applications").select("job_id").eq("seeker_id", seeker_id).execute().data or [])}
    except Exception:
        return {a["job_id"] for a in _test_applications if a.get("seeker_id") == seeker_id}


def add_application(seeker_id, job_id, cover_note=""):
    if any(a["seeker_id"] == seeker_id and a["job_id"] == job_id for a in _test_applications):
        return False
    _test_applications.append({
        "id": len(_test_applications) + 1,
        "seeker_id": seeker_id,
        "job_id": job_id,
        "cover_note": cover_note,
        "applied_at": _now(),
        "stage": "New",
        "status": "Applied"
    })
    if not _is_test_or_unconfigured():
        try:
            if get_db().table("applications").select("id").eq("seeker_id", seeker_id).eq("job_id", job_id).limit(1).execute().data:
                return False
            get_db().table("applications").insert({"seeker_id": seeker_id, "job_id": job_id, "cover_note": cover_note}).execute()
        except Exception:
            pass
    return True


def get_application(seeker_id, application_id):
    for a in _test_applications:
        if a.get("id") == application_id and a.get("seeker_id") == seeker_id:
            return a
    return _one("applications", id=application_id, seeker_id=seeker_id)


def set_application_status(seeker_id, application_id, status):
    app = get_application(seeker_id, application_id)
    if app:
        app["status"] = status
    if not _is_test_or_unconfigured():
        try:
            get_db().table("applications").update({"status": status, "updated_at": _now()}).eq("id", application_id).eq("seeker_id", seeker_id).execute()
        except Exception:
            pass
    return bool(app)


def remove_application(seeker_id, application_id):
    global _test_applications
    initial_len = len(_test_applications)
    _test_applications = [a for a in _test_applications if not (a.get("id") == application_id and a.get("seeker_id") == seeker_id)]
    if not _is_test_or_unconfigured():
        try:
            get_db().table("applications").delete().eq("id", application_id).eq("seeker_id", seeker_id).execute()
        except Exception:
            pass
    return len(_test_applications) < initial_len


def saved_job_ids(seeker_id):
    if _is_test_or_unconfigured():
        return [j for (s, j) in _test_saved_jobs if s == seeker_id]
    try:
        return [r["job_id"] for r in (get_db().table("saved_jobs").select("job_id").eq("seeker_id", seeker_id).order("saved_at", desc=True).execute().data or [])]
    except Exception:
        return [j for (s, j) in _test_saved_jobs if s == seeker_id]


def toggle_saved(seeker_id, job_id):
    pair = (seeker_id, job_id)
    saved = False
    if pair in _test_saved_jobs:
        _test_saved_jobs.remove(pair)
        saved = False
    else:
        _test_saved_jobs.add(pair)
        saved = True

    if not _is_test_or_unconfigured():
        try:
            row = _one("saved_jobs", seeker_id=seeker_id, job_id=job_id)
            if row:
                get_db().table("saved_jobs").delete().eq("seeker_id", seeker_id).eq("job_id", job_id).execute()
            else:
                get_db().table("saved_jobs").insert({"seeker_id": seeker_id, "job_id": job_id}).execute()
        except Exception:
            pass
    return saved


def format_date(value):
    try:
        d = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        return f"{d.day} {d:%b %Y}"
    except (ValueError, TypeError):
        return value or ""
