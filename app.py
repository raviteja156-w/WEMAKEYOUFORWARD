import hmac
import os
import secrets
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, flash, render_template, session, jsonify, request, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import stripe
except ImportError:
    stripe = None

import data
import db
import job_store
import employer_auth
import seeker_auth
import seeker_portal
import seeker_store as store
import security
from employer_auth import current_company, current_employer, employer_required
from seeker_auth import current_seeker, seeker_required

app = Flask(__name__)

# --- Security / session config -------------------------------------------------
is_prod = os.environ.get("FLASK_ENV") == "production" or os.environ.get("RENDER") or os.environ.get("PRODUCTION") == "1"
secret_key_val = os.environ.get("SECRET_KEY")
if is_prod and (not secret_key_val or "change-me" in secret_key_val or len(secret_key_val) < 16):
    raise RuntimeError("FATAL: SECRET_KEY environment variable is required in production to maintain persistent user sessions across server restarts.")
app.secret_key = secret_key_val or secrets.token_hex(32)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
# Trust one proxy hop (Render, Heroku, nginx) so https URLs and client IPs are correct.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

db.init_app(app)
security.install_security(app)

# First run: copy the sample job board into Supabase so job search has test data.
if app.config.get("SUPABASE_CONFIGURED"):
    with app.app_context():
        try:
            added = job_store.seed_demo_jobs(data.build_seed_jobs, data.DEMO_REPORTS)
            if added:
                app.logger.warning("Seeded %s sample jobs into Supabase.", added)
        except Exception as exc:  # table missing -> tell the developer what to run
            app.logger.error("Jobs table not ready (%s). Run supabase/migration_002_jobs.sql in Supabase.", exc)
app.register_blueprint(employer_auth.bp)
app.register_blueprint(seeker_auth.bp)
app.register_blueprint(seeker_portal.api_bp)


def is_admin_authenticated():
    if session.get("is_admin") is True:
        return True
    if app.config.get("TESTING") and session.get("demo_role") == "admin":
        return True
    admin_emails = [e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
    if admin_emails:
        emp = current_employer()
        if emp and emp.get("email", "").lower() in admin_emails:
            return True
        seek = current_seeker()
        if seek and seek.get("email", "").lower() in admin_emails:
            return True
    return False


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin_authenticated():
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Administrator authentication required."}), 403
            flash("Administrator login required to access staff portals.", "error")
            return redirect(url_for("admin_login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def current_role():
    if is_admin_authenticated():
        return "admin"
    return session.get("demo_role", "guest")


@app.context_processor
def inject_globals():
    employer = current_employer()
    seeker_row = None if employer else current_seeker()
    if employer:
        role = "employer"          # a real login always wins over the demo switcher
    elif seeker_row:
        role = "seeker"
    elif is_admin_authenticated():
        role = "admin"
    else:
        role = current_role()
        if role in ("employer", "seeker"):
            role = "guest"         # these views can no longer be faked
    return {
        "demo_role": role,
        "demo_mode": bool(os.environ.get("DEMO_MODE") == "1" or app.config.get("DEMO_MODE", False)),
        "is_admin": is_admin_authenticated(),
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
    live = data.live_jobs()
    featured_jobs = [j for j in live if j["featured"]][:6]
    categories = {}
    for j in live:
        categories.setdefault(j["industry"], 0)
        categories[j["industry"]] += 1
    return render_template("index.html", featured_jobs=featured_jobs, categories=categories,
                            salary_label=data.salary_label)


@app.route("/jobs")
def jobs():
    live_jobs = data.live_jobs()
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
        count = sum(1 for j in data.live_jobs() if j["company"] == c["name"])
        items.append({**c, "open_roles": count})
    return render_template("companies.html", companies=items)


@app.route("/companies/<slug>")
def company_jobs(slug):
    company = next((c for c in TOP_COMPANIES if c["slug"] == slug), None)
    if not company:
        return render_template("404.html"), 404
    posted = [j for j in data.live_jobs() if j["company"] == company["name"]]
    return render_template("company_jobs.html", company=company, jobs=posted, salary_label=data.salary_label)


@app.route("/jobs/<int:job_id>")
def job_details(job_id):
    job = data.get_job(job_id)
    employer = current_employer()
    # Drafts / pending / rejected jobs are only visible to the employer who owns them.
    if not job or (job["status"] != "Approved" and not (employer and job_store._owns(employer, job))):
        return render_template("404.html"), 404
    if not (employer and job_store._owns(employer, job)):
        job_store.add_view(job_id)
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
    similar = [j for j in data.live_jobs() if j["industry"] == job["industry"] and j["id"] != job_id][:3]
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
    matching_alerts = seeker_portal.matching_alerts_for_seeker(ctx["row"]["id"])
    return render_template("seeker_dashboard.html", **ctx, applications=apps, status_counts=counts,
                           saved=saved, statuses=store.APPLICATION_STATUSES,
                           matching_alerts=matching_alerts,
                           resume_updated=store.format_date(ctx["resume"]["updated_at"]) if ctx["resume"] else "",
                           salary_label=data.salary_label)


@app.route("/dashboard/employer")
@employer_required
def employer_dashboard():
    employer = current_employer()
    my_jobs = sorted(data.jobs_for_employer(employer), key=lambda j: j["posted_days_ago"])
    live_jobs = [j for j in my_jobs if j["status"] == "Approved"]
    my_candidates = data.candidates_for_employer(employer)
    shortlisted = sum(1 for c in my_candidates if c["stage"] in ("Shortlisted", "Interview", "Hired"))
    recent_applicants = sorted(my_candidates, key=lambda c: c["applied_date"], reverse=True)[:5]
    return render_template(
        "employer_dashboard.html", company=current_company(), my_jobs=my_jobs,
        active_jobs=len(live_jobs),
        total_views=sum(j.get("views", 0) or 0 for j in my_jobs),
        total_apps=sum(j.get("applications_count", 0) or 0 for j in my_jobs),
        shortlisted=shortlisted, recent_applicants=recent_applicants)


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
    latest = job_store.latest_draft(current_employer())
    draft = {"job_id": latest["id"], "title": latest["title"]} if latest else {}
    return render_template("checkout.html", package=package, draft=draft)


@app.route("/applicants")
@employer_required
def applicants():
    mine = data.candidates_for_employer(current_employer())
    grouped = {s: [c for c in mine if c["stage"] == s] for s in data.STAGES}
    return render_template("applicants.html", grouped=grouped, stages=data.STAGES)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if is_admin_authenticated():
        return redirect(url_for("admin"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        expected_email = (os.environ.get("ADMIN_EMAIL") or "admin@nexora.com.au").strip().lower()
        expected_pw = os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_SECRET_KEY") or "NexoraAdmin2026!"

        valid_email = hmac.compare_digest(email, expected_email)
        valid_pw = hmac.compare_digest(password, expected_pw)

        if valid_email and valid_pw:
            session.clear()
            session["is_admin"] = True
            session.permanent = True
            flash("Authenticated as Administrator.", "success")
            next_url = request.args.get("next")
            return redirect(next_url if next_url and next_url.startswith("/") else url_for("admin"))
        else:
            flash("Invalid administrator credentials.", "error")
    return render_template("admin_login.html")


@app.post("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin signed out.", "info")
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    every_job = [j for j in data.all_jobs() if j["status"] != "Draft"]
    live_jobs = [j for j in every_job if j["status"] == "Approved"]
    pending_jobs = [j for j in every_job if j["status"] == "Pending"]
    rejected_jobs = [j for j in every_job if j["status"] == "Rejected"]
    stats = job_store.platform_stats()
    return render_template("admin.html", stats=stats, live_jobs=live_jobs,
                            pending_jobs=pending_jobs, rejected_jobs=rejected_jobs,
                            all_jobs=every_job, reports=job_store.reports(), revenue=stats["revenue_month"])


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/") or request.headers.get("Accept") == "application/json":
        return jsonify({"ok": False, "error": "Resource not found."}), 404
    return render_template("404.html"), 404


# --------------------------------------------------------------- API ----
@app.post("/api/demo-role")
def api_demo_role():
    if not app.config.get("TESTING") and os.environ.get("DEMO_MODE") != "1":
        return jsonify({"ok": False, "error": "Demo mode is disabled in production."}), 403
    role = (request.json or {}).get("role", "guest")
    if role not in ("guest", "seeker", "admin", "employer"):
        return jsonify({"ok": False}), 400
    for key in ("employer_id", "seeker_id"):
        session.pop(key, None)
    session["demo_role"] = role if role in ("guest", "admin") else "guest"
    return jsonify({"ok": True, "role": role})


@app.post("/api/post-job")
@employer_required
def api_post_job():
    payload = request.json or {}
    employer, company = current_employer(), current_company()
    def money(key, default):
        try:
            return max(0, min(10_000_000, int(float(payload.get(key) or default))))
        except (TypeError, ValueError):
            return default

    def pick(key, options):
        value = payload.get(key)
        return value if value in options else options[0]

    title = (str(payload.get("title") or "").strip() or "Untitled role")[:120]
    salary_min, salary_max = money("salary_min", 60000), money("salary_max", 90000)
    if salary_max < salary_min:
        salary_min, salary_max = salary_max, salary_min
    closing = str(payload.get("closing_date") or "")[:10]
    try:
        closing = date.fromisoformat(closing).isoformat()
    except ValueError:
        closing = (date.today() + timedelta(days=30)).isoformat()
    experience = pick("experience", data.EXPERIENCE_LEVELS)
    job_id = job_store.create_job({
        "employer_id": employer["id"],
        "is_demo": False,
        "title": title,
        "company": company["name"],
        "company_initials": company["initials"],
        "company_color": company["color"],
        "location": pick("location", data.LOCATIONS),
        "type": pick("type", data.JOB_TYPES),
        "mode": pick("mode", data.WORK_MODES),
        "experience": experience,
        "industry": pick("industry", data.INDUSTRIES),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "tags": [t.strip()[:40] for t in str(payload.get("skills", "")).split(",") if t.strip()][:6] or ["General"],
        "closing_date": closing,
        "featured": False,
        "urgent": False,
        "status": "Draft",
        "views": 0,
        "about_role": (str(payload.get("description") or "").strip() or "Description coming soon.")[:5000],
        "responsibilities": ["Deliver against role objectives", "Work closely with the team"],
        "requirements": [f"Experience level: {experience}"],
        "benefits": ["Flexible working arrangements"],
        "about_company": f"{company['name']} is hiring through NEXORA.",
    })
    return jsonify({"ok": True, "job_id": job_id})


@app.post("/api/checkout")
@employer_required
def api_checkout():
    payload = request.json or {}
    employer = current_employer()
    job = job_store.latest_draft(employer)
    package = next((p for p in data.PACKAGES if p["id"] == payload.get("package")), data.PACKAGES[1])
    if not job:
        return jsonify({"ok": False, "error": "No draft job to publish."}), 404

    stripe_key = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if stripe and stripe_key and not stripe_key.startswith("sk_test_replace"):
        try:
            stripe.api_key = stripe_key
            success_url = url_for("checkout_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}"
            cancel_url = url_for("checkout", package=package["id"], _external=True)
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "aud",
                        "product_data": {
                            "name": f"NEXORA {package['name']} Job Listing (30 Days)",
                            "description": f"Publish '{job['title']}' on the NEXORA Australian hiring directory.",
                        },
                        "unit_amount": int(package["price"] * 100),
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=str(employer["id"]),
                metadata={
                    "job_id": str(job["id"]),
                    "employer_id": str(employer["id"]),
                    "package_id": str(package["id"]),
                }
            )
            job_store.record_order(employer["id"], job["id"], package)
            return jsonify({"ok": True, "checkout_url": checkout_session.url, "session_id": checkout_session.id})
        except Exception as exc:
            app.logger.error("Stripe checkout session creation failed: %s", exc)
            return jsonify({"ok": False, "error": f"Payment initialization error: {str(exc)}"}), 502

    # Under automated testing or when DEMO_MODE=1 is explicitly turned on
    if app.config.get("TESTING") or os.environ.get("DEMO_MODE") == "1":
        job_store.update_job(job["id"], status="Approved", package=package["id"],
                             featured=package["id"] in ("featured", "premium"),
                             urgent=package["id"] in ("urgent", "premium"))
        job_store.record_order(employer["id"], job["id"], package)
        return jsonify({"ok": True, "job_id": job["id"], "demo_mode": True})

    return jsonify({
        "ok": False,
        "error": "Online payment is not configured. Please set STRIPE_SECRET_KEY in your hosting dashboard."
    }), 503


@app.post("/api/stripe/webhook")
def stripe_webhook():
    webhook_secret = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    if not stripe or not webhook_secret:
        return jsonify({"ok": False, "error": "Stripe webhook not configured"}), 400
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:
        app.logger.warning("Stripe webhook signature validation failed: %s", exc)
        return jsonify({"ok": False, "error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        metadata = session_obj.get("metadata") or {}
        job_id = metadata.get("job_id")
        package_id = metadata.get("package_id", "basic")
        employer_id = metadata.get("employer_id") or session_obj.get("client_reference_id")
        package = next((p for p in data.PACKAGES if p["id"] == package_id), data.PACKAGES[0])
        if job_id:
            job_store.update_job(int(job_id), status="Approved", package=package_id,
                                 featured=package_id in ("featured", "premium"),
                                 urgent=package_id in ("urgent", "premium"))
            if employer_id:
                job_store.record_order(int(employer_id), int(job_id), package)
            app.logger.info("Stripe payment confirmed for Job %s. Marked Approved.", job_id)

    return jsonify({"ok": True, "received": True})


@app.route("/checkout/success")
@employer_required
def checkout_success():
    return render_template("checkout_success.html")


@app.post("/api/applicants/<int:candidate_id>/stage")
@employer_required
def api_move_stage(candidate_id):
    new_stage = (request.json or {}).get("stage")
    if job_store.move_stage(current_employer(), candidate_id, new_stage):
        return jsonify({"ok": True, "stage": new_stage})
    return jsonify({"ok": False}), 404


@app.post("/api/admin/jobs/<int:job_id>/moderate")
@admin_required
def api_moderate(job_id):
    action = (request.json or {}).get("action")
    job = data.get_job(job_id)
    if not job:
        return jsonify({"ok": False}), 404
    mapping = {"approve": "Approved", "reject": "Rejected", "review": "Review", "suspend": "Suspended"}
    if action in mapping:
        job_store.update_job(job_id, status=mapping[action])
        return jsonify({"ok": True, "status": mapping[action]})
    return jsonify({"ok": False}), 400


@app.post("/api/admin/reports/<int:report_id>/resolve")
@admin_required
def api_resolve_report(report_id):
    if job_store.resolve_report(report_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


@app.route("/interview")
@app.route("/interview-practice")
def top_interview_redirect():
    return redirect(url_for("seeker.interview_practice"))


@app.route("/resume")
def top_resume_redirect():
    return redirect(url_for("seeker.resume"))


@app.route("/alerts")
def top_alerts_redirect():
    return redirect(url_for("seeker.alerts"))


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
