import os
import secrets
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, session, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

import data
import db
import employer_auth
import seeker_auth
import seeker_portal
import seeker_store as store
from employer_auth import current_company, current_employer, employer_required
from seeker_auth import current_seeker, seeker_required

app = Flask(__name__)

# --- Security / session config -------------------------------------------------
# Set SECRET_KEY in the environment for production. Without it a random key is used,
# which is fine locally but signs everyone out whenever the server restarts.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set SESSION_COOKIE_SECURE=1 on any https deployment (render.yaml does this).
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=1024 * 1024,
)
# Trust one proxy hop (Render, Heroku, nginx) so https URLs and client IPs are correct.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

db.init_app(app)
app.register_blueprint(employer_auth.bp)
app.register_blueprint(seeker_auth.bp)
app.register_blueprint(seeker_portal.api_bp)


def current_role():
    return session.get("demo_role", "guest")


@app.context_processor
def inject_globals():
    employer = current_employer()
    seeker_row = None if employer else current_seeker()
    if employer:
        role = "employer"          # a real login always wins over the demo switcher
    elif seeker_row:
        role = "seeker"
    else:
        role = current_role()
        if role in ("employer", "seeker"):
            role = "guest"         # these views can no longer be faked
    return {
        "demo_role": role,
        "employer_user": employer,
        "employer_company": current_company(),
        "seeker_user": store.seeker_display(seeker_row) if seeker_row else None,
        "csrf_token": employer_auth.csrf_token,
        "saved_count": len(store.saved_job_ids(seeker_row["id"])) if seeker_row else 0,
    }


@app.template_filter("posted_label")
def posted_label(days):
    if days <= 0:
        return "Today"
    if days < 30:
        return f"{days}d ago"
    return f"{days // 30}mo ago"


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.path.startswith(("/employer", "/dashboard/employer")):
        resp.headers["Cache-Control"] = "no-store"  # don't cache account pages (back button after logout)
    return resp


# ---------------------------------------------------------------- pages --
@app.route("/")
def index():
    featured_jobs = [j for j in data.JOBS if j["status"] == "Approved" and j["featured"]][:6]
    categories = {}
    for j in data.JOBS:
        categories.setdefault(j["industry"], 0)
        categories[j["industry"]] += 1
    return render_template("index.html", featured_jobs=featured_jobs, categories=categories,
                            salary_label=data.salary_label)


@app.route("/jobs")
def jobs():
    live_jobs = [j for j in data.JOBS if j["status"] == "Approved"]
    return render_template(
        "jobs.html",
        jobs_json=live_jobs,
        saved_ids=store.saved_job_ids(current_seeker()["id"]) if current_seeker() else [],
        applied_ids=list(store.applied_job_ids(current_seeker()["id"])) if current_seeker() else [],
        locations=data.LOCATIONS,
        industries=data.INDUSTRIES,
        job_types=data.JOB_TYPES,
        work_modes=data.WORK_MODES,
        experience_levels=data.EXPERIENCE_LEVELS,
        salary_label=data.salary_label,
    )


TOP_COMPANIES = [
    {"slug": "northlane-digital", "name": "Northlane Digital", "initials": "ND", "color": "#5D4FE0",
     "industry": "Technology", "location": "Melbourne, VIC", "employees": "250-500",
     "about": "A product engineering studio building web and mobile platforms for Australian brands."},
    {"slug": "harbourfield-health", "name": "Harbourfield Health", "initials": "HH", "color": "#2DD9B8",
     "industry": "Healthcare", "location": "Brisbane, QLD", "employees": "1,000+",
     "about": "A leading healthcare network delivering compassionate, community-focused patient care."},
    {"slug": "ferro-cole-construction", "name": "Ferro & Cole Construction", "initials": "FC", "color": "#0B1230",
     "industry": "Construction", "location": "Perth, WA", "employees": "500-1,000",
     "about": "Commercial and civil construction specialists delivering landmark projects nationwide."},
    {"slug": "bright-retail-co", "name": "Bright Retail Co.", "initials": "BR", "color": "#E0975D",
     "industry": "Retail", "location": "Adelaide, SA", "employees": "100-250",
     "about": "A fast-growing retail group with stores and online experiences across Australia."},
]


@app.route("/companies")
def companies():
    items = []
    for c in TOP_COMPANIES:
        count = sum(1 for j in data.JOBS if j["status"] == "Approved" and j["company"] == c["name"])
        items.append({**c, "open_roles": count})
    return render_template("companies.html", companies=items)


@app.route("/companies/<slug>")
def company_jobs(slug):
    company = next((c for c in TOP_COMPANIES if c["slug"] == slug), None)
    if not company:
        return render_template("404.html"), 404
    posted = [j for j in data.JOBS if j["status"] == "Approved" and j["company"] == company["name"]]
    return render_template("company_jobs.html", company=company, jobs=posted, salary_label=data.salary_label)


@app.route("/jobs/<int:job_id>")
def job_details(job_id):
    job = data.get_job(job_id)
    if not job:
        return render_template("404.html"), 404
    me = current_seeker()
    is_saved = has_applied = False
    percent, resume_info = 0, None
    if me:
        is_saved = job_id in store.saved_job_ids(me["id"])
        has_applied = job_id in store.applied_job_ids(me["id"])
        profile = store.get_profile(me["id"])
        percent = store.profile_completion(me, profile)[0]
        resume_info = store.get_resume(me["id"])
        if resume_info:
            resume_info["updated_label"] = store.format_date(resume_info["updated_at"])
    similar = [j for j in data.JOBS if j["industry"] == job["industry"] and j["id"] != job_id][:3]
    return render_template("job_details.html", job=job, is_saved=is_saved, has_applied=has_applied,
                           similar=similar, profile_percent=percent, resume_info=resume_info,
                           salary_label=data.salary_label)


@app.route("/dashboard/seeker")
@seeker_required
def seeker_dashboard():
    ctx = seeker_portal.portal_context()
    apps = seeker_portal._applications_view(ctx["row"]["id"])
    counts = {st: sum(1 for a in apps if a["status"] == st) for st in store.APPLICATION_STATUSES}
    saved = [j for j in (data.get_job(i) for i in store.saved_job_ids(ctx["row"]["id"])) if j]
    return render_template("seeker_dashboard.html", **ctx, applications=apps, status_counts=counts,
                           saved=saved, statuses=store.APPLICATION_STATUSES,
                           resume_updated=store.format_date(ctx["resume"]["updated_at"]) if ctx["resume"] else "",
                           salary_label=data.salary_label)


@app.route("/dashboard/employer")
@app.route("/employer_dashboard")
@employer_required
def employer_dashboard():
    employer = current_employer()
    my_jobs = sorted(data.jobs_for_employer(employer), key=lambda j: j["posted_days_ago"])
    live_jobs = [j for j in my_jobs if j["status"] == "Approved"]
    my_candidates = data.candidates_for_employer(employer)
    shortlisted = sum(1 for c in my_candidates if c.get("stage") in ("Shortlisted", "Interview", "Hired"))
    interviews = sum(1 for c in my_candidates if c.get("stage") == "Interview")
    hired = sum(1 for c in my_candidates if c.get("stage") == "Hired")
    recent_applicants = sorted(my_candidates, key=lambda c: c.get("applied_date", ""), reverse=True)[:5]
    return render_template(
        "employer_dashboard.html", company=current_company(), my_jobs=my_jobs,
        active_jobs=len(live_jobs),
        total_views=sum(j["views"] for j in my_jobs),
        total_apps=sum(j["applications_count"] for j in my_jobs),
        shortlisted=shortlisted,
        interviews_count=interviews,
        hired_count=hired,
        recent_applicants=recent_applicants)


@app.route("/post-job")
@employer_required
def post_job():
    return render_template("post_job.html", industries=data.INDUSTRIES, job_types=data.JOB_TYPES,
                            work_modes=data.WORK_MODES, experience_levels=data.EXPERIENCE_LEVELS,
                            locations=data.LOCATIONS)


@app.route("/pricing")
def pricing():
    return render_template("pricing.html", packages=data.PACKAGES)


@app.route("/checkout")
@employer_required
def checkout():
    package_id = request.args.get("package", "featured")
    package = next((p for p in data.PACKAGES if p["id"] == package_id), data.PACKAGES[1])
    draft = data.DRAFT_JOBS.get(current_employer()["id"], {})
    return render_template("checkout.html", package=package, draft=draft)


@app.route("/applicants")
@employer_required
def applicants():
    mine = data.candidates_for_employer(current_employer())
    grouped = {s: [c for c in mine if c["stage"] == s] for s in data.STAGES}
    return render_template("applicants.html", grouped=grouped, stages=data.STAGES)


@app.route("/admin")
def admin():
    live_jobs = [j for j in data.JOBS if j["status"] == "Approved"]
    pending_jobs = [j for j in data.JOBS if j["status"] == "Pending"]
    rejected_jobs = [j for j in data.JOBS if j["status"] == "Rejected"]
    revenue = data.PLATFORM_STATS["revenue_month"]
    return render_template("admin.html", stats=data.PLATFORM_STATS, live_jobs=live_jobs,
                            pending_jobs=pending_jobs, rejected_jobs=rejected_jobs,
                            all_jobs=data.JOBS, reports=data.ADMIN_REPORTS, revenue=revenue)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# --------------------------------------------------------------- API ----
@app.post("/api/demo-role")
def api_demo_role():
    role = (request.json or {}).get("role", "guest")
    if role not in ("guest", "seeker", "admin", "employer"):
        return jsonify({"ok": False}), 400
    # Employer and job-seeker access are real now: those dashboards send visitors to a login page.
    # Choosing a different persona leaves any account you were signed in to.
    for key in ("employer_id", "seeker_id"):
        session.pop(key, None)
    session["demo_role"] = role if role in ("guest", "admin") else "guest"
    return jsonify({"ok": True, "role": role})


@app.post("/api/post-job")
@employer_required
def api_post_job():
    payload = request.json or {}
    employer, company = current_employer(), current_company()
    job = {
        "id": data.next_id(),
        "employer_id": employer["id"],
        "title": payload.get("title", "Untitled role"),
        "company": company["name"],
        "company_initials": company["initials"],
        "company_color": company["color"],
        "location": payload.get("location", data.LOCATIONS[0]),
        "type": payload.get("type", data.JOB_TYPES[0]),
        "mode": payload.get("mode", data.WORK_MODES[0]),
        "experience": payload.get("experience", data.EXPERIENCE_LEVELS[0]),
        "industry": payload.get("industry", data.INDUSTRIES[0]),
        "salary_min": int(payload.get("salary_min") or 60000),
        "salary_max": int(payload.get("salary_max") or 90000),
        "tags": [t.strip() for t in payload.get("skills", "").split(",") if t.strip()][:6] or ["General"],
        "posted_days_ago": 0,
        "closing_date": payload.get("closing_date", (date.today() + timedelta(days=30)).isoformat()),
        "featured": False,
        "urgent": False,
        "status": "Draft",
        "views": 0,
        "applications_count": 0,
        "about_role": payload.get("description", "Description coming soon."),
        "responsibilities": ["Deliver against role objectives", "Work closely with the team"],
        "requirements": [f"Experience level: {payload.get('experience', 'Not specified')}"],
        "benefits": ["Flexible working arrangements"],
        "about_company": f"{company['name']} is hiring through NEXORA.",
    }
    data.JOBS.append(job)
    data.DRAFT_JOBS[employer["id"]] = {"job_id": job["id"], "title": job["title"]}
    return jsonify({"ok": True, "job_id": job["id"]})


@app.post("/api/checkout")
@employer_required
def api_checkout():
    payload = request.json or {}
    employer = current_employer()
    job_id = data.DRAFT_JOBS.get(employer["id"], {}).get("job_id")
    job = data.get_job(job_id) if job_id else None
    package_id = payload.get("package", "featured")
    if job and job.get("employer_id") == employer["id"]:
        job["status"] = "Approved"
        job["featured"] = package_id in ("featured", "premium")
        job["urgent"] = package_id == "urgent"
    return jsonify({"ok": True, "job_id": job_id})


@app.post("/api/applicants/<int:candidate_id>/stage")
@employer_required
def api_move_stage(candidate_id):
    new_stage = (request.json or {}).get("stage")
    for c in data.candidates_for_employer(current_employer()):
        if c["id"] == candidate_id and new_stage in data.STAGES:
            c["stage"] = new_stage
            return jsonify({"ok": True, "stage": new_stage})
    return jsonify({"ok": False}), 404


@app.post("/api/admin/jobs/<int:job_id>/moderate")
def api_moderate(job_id):
    action = (request.json or {}).get("action")
    job = data.get_job(job_id)
    if not job:
        return jsonify({"ok": False}), 404
    mapping = {"approve": "Approved", "reject": "Rejected", "review": "Review", "suspend": "Suspended"}
    if action in mapping:
        job["status"] = mapping[action]
        return jsonify({"ok": True, "status": job["status"]})
    return jsonify({"ok": False}), 400


# ------------------------------------------------------------------ CLI --
@app.cli.command("seed-demo")
def seed_demo_command():
    """Create the demo employer (Northlane Digital) and demo job seeker (Jordan Reyes)."""
    import click
    password = os.environ.get("DEMO_EMPLOYER_PASSWORD") or secrets.token_urlsafe(9) + "7"
    employer_auth.seed_demo(password)
    seeker_auth.seed_demo(password)
    click.echo(f"Demo employer ready:   {employer_auth.DEMO_EMAIL} / {password}")
    click.echo(f"Demo job seeker ready: {seeker_auth.DEMO_EMAIL} / {password}")


# Optional: auto-create the demo employer on boot (handy on hosts with an ephemeral database).
if os.environ.get("NEXORA_SEED_DEMO") == "1" and os.environ.get("DEMO_EMPLOYER_PASSWORD"):
    with app.app_context():
        employer_auth.seed_demo(os.environ["DEMO_EMPLOYER_PASSWORD"])
        seeker_auth.seed_demo(os.environ["DEMO_EMPLOYER_PASSWORD"])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
