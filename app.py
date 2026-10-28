from datetime import date, timedelta
from flask import Flask, render_template, session, jsonify, request

import data

app = Flask(__name__)
app.secret_key = "nexora-demo-secret-key"


def current_role():
    return session.get("demo_role", "guest")


@app.context_processor
def inject_globals():
    return {
        "demo_role": current_role(),
        "saved_count": len(data.SEEKER_SAVED_JOB_IDS),
    }


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
        saved_ids=list(data.SEEKER_SAVED_JOB_IDS),
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
    is_saved = job_id in data.SEEKER_SAVED_JOB_IDS
    has_applied = any(a["job_id"] == job_id for a in data.SEEKER_APPLICATIONS)
    similar = [j for j in data.JOBS if j["industry"] == job["industry"] and j["id"] != job_id][:3]
    return render_template("job_details.html", job=job, is_saved=is_saved, has_applied=has_applied,
                            similar=similar, seeker=data.SEEKER, salary_label=data.salary_label)


@app.route("/dashboard/seeker")
def seeker_dashboard():
    apps = []
    for a in data.SEEKER_APPLICATIONS:
        job = data.get_job(a["job_id"])
        if job:
            apps.append({**a, "job": job})
    saved = [data.get_job(jid) for jid in data.SEEKER_SAVED_JOB_IDS if data.get_job(jid)]
    recommended = [j for j in data.JOBS
                   if j["status"] == "Approved"
                   and any(t in data.SEEKER["skills"] for t in j["tags"])
                   and j["id"] not in [a["job_id"] for a in data.SEEKER_APPLICATIONS]][:3]
    for i, j in enumerate(recommended):
        j["_match"] = 92 - i * 6
    pipeline_counts = {s: sum(1 for a in apps if a["stage"] == s) for s in data.APPLICATION_STAGES}
    return render_template("seeker_dashboard.html", seeker=data.SEEKER, applications=apps,
                            saved=saved, recommended=recommended, stages=data.APPLICATION_STAGES,
                            pipeline_counts=pipeline_counts, salary_label=data.salary_label)


@app.route("/dashboard/employer")
def employer_dashboard():
    my_jobs = [j for j in data.JOBS if j["id"] in data.EMPLOYER["jobs_posted_ids"]]
    total_views = sum(j["views"] for j in my_jobs)
    total_apps = sum(j["applications_count"] for j in my_jobs)
    shortlisted = sum(1 for c in data.CANDIDATES if c["stage"] in ("Shortlisted", "Interview", "Hired"))
    recent_applicants = sorted(data.CANDIDATES, key=lambda c: c["applied_date"], reverse=True)[:5]
    return render_template("employer_dashboard.html", employer=data.EMPLOYER, my_jobs=my_jobs,
                            total_views=total_views, total_apps=total_apps, shortlisted=shortlisted,
                            recent_applicants=recent_applicants, salary_label=data.salary_label)


@app.route("/post-job")
def post_job():
    return render_template("post_job.html", industries=data.INDUSTRIES, job_types=data.JOB_TYPES,
                            work_modes=data.WORK_MODES, experience_levels=data.EXPERIENCE_LEVELS,
                            locations=data.LOCATIONS)


@app.route("/pricing")
def pricing():
    return render_template("pricing.html", packages=data.PACKAGES)


@app.route("/checkout")
def checkout():
    package_id = request.args.get("package", "featured")
    package = next((p for p in data.PACKAGES if p["id"] == package_id), data.PACKAGES[1])
    return render_template("checkout.html", package=package, draft=data.DRAFT_JOB)


@app.route("/applicants")
def applicants():
    grouped = {s: [c for c in data.CANDIDATES if c["stage"] == s] for s in data.STAGES}
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
    role = request.json.get("role", "guest")
    session["demo_role"] = role
    return jsonify({"ok": True, "role": role})


@app.post("/api/jobs/<int:job_id>/save")
def api_toggle_save(job_id):
    if job_id in data.SEEKER_SAVED_JOB_IDS:
        data.SEEKER_SAVED_JOB_IDS.discard(job_id)
        saved = False
    else:
        data.SEEKER_SAVED_JOB_IDS.add(job_id)
        saved = True
    return jsonify({"ok": True, "saved": saved, "saved_count": len(data.SEEKER_SAVED_JOB_IDS)})


@app.post("/api/jobs/<int:job_id>/apply")
def api_apply(job_id):
    if not any(a["job_id"] == job_id for a in data.SEEKER_APPLICATIONS):
        data.SEEKER_APPLICATIONS.append({
            "job_id": job_id, "stage": "Applied",
            "applied_date": date.today().isoformat(),
        })
        job = data.get_job(job_id)
        if job:
            job["applications_count"] += 1
    return jsonify({"ok": True})


@app.post("/api/post-job")
def api_post_job():
    payload = request.json or {}
    job = {
        "id": data.next_id(),
        "title": payload.get("title", "Untitled role"),
        "company": data.EMPLOYER["company"],
        "company_initials": data.EMPLOYER["initials"],
        "company_color": data.EMPLOYER["color"],
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
        "about_company": f"{data.EMPLOYER['company']} is hiring through NEXORA.",
    }
    data.JOBS.append(job)
    data.DRAFT_JOB.clear()
    data.DRAFT_JOB.update({"job_id": job["id"], "title": job["title"]})
    return jsonify({"ok": True, "job_id": job["id"]})


@app.post("/api/checkout")
def api_checkout():
    payload = request.json or {}
    job_id = data.DRAFT_JOB.get("job_id")
    job = data.get_job(job_id) if job_id else None
    package_id = payload.get("package", "featured")
    if job:
        job["status"] = "Approved"
        job["featured"] = package_id in ("featured", "premium")
        job["urgent"] = package_id == "urgent"
        if job_id not in data.EMPLOYER["jobs_posted_ids"]:
            data.EMPLOYER["jobs_posted_ids"].append(job_id)
    return jsonify({"ok": True, "job_id": job_id})


@app.post("/api/applicants/<int:candidate_id>/stage")
def api_move_stage(candidate_id):
    new_stage = (request.json or {}).get("stage")
    for c in data.CANDIDATES:
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
