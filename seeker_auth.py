"""
Job-seeker authentication. Mirrors the employer flow and reuses the same shared templates
(templates/auth/) and helpers (auth_common), so both sides look and behave identically.

Routes (all under /seeker):
    GET/POST  /register       Create a job-seeker account
    GET/POST  /login          Sign in
    POST      /logout         Sign out
    GET/POST  /forgot         Request a password-reset link
    GET/POST  /reset/<token>  Choose a new password
    GET       /google         Start "Continue with Google"
    GET       /google/callback

Portal pages (profile, applications, resume, matches, upgrade) live in seeker_portal.py.
"""
import hmac
import os
import secrets
from functools import wraps

from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

import auth_common as ac
import seeker_store as store
import validators as v
from auth_common import safe_next

bp = Blueprint("seeker", __name__, url_prefix="/seeker")

RESET_SALT = "seeker-password-reset"
CFG = {
    "bp": "seeker",
    "page_label": "Job seeker",
    "ask_name": True,
    "register_title": "Create your account",
    "register_sub": "Get matched with roles that fit your skills and experience.",
    "login_page_title": "Job seeker login",
    "login_sub": "Sign in to track applications, build your resume and see your best matches.",
    "other_bp": "employer",
    "other_prompt": "Hiring?",
    "other_label": "Create an employer account",
    "other_login_label": "Employer login",
}


# ------------------------------------------------------------- helpers --
def current_seeker():
    """The signed-in seeker row, or None. Cached for the request."""
    if "seeker" not in g:
        g.seeker = store.get_seeker(session.get("seeker_id"))
        if g.seeker is None:
            session.pop("seeker_id", None)
    return g.seeker


def seeker_required(view):
    """Require a signed-in job seeker (page routes redirect, /api/ routes return JSON errors)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_seeker():
            if ac.wants_json():
                if session.get("employer_id"):
                    return jsonify({"ok": False, "error": "Employers can't do this. Use a job seeker account."}), 403
                return jsonify({"ok": False, "error": "Please log in."}), 401
            flash("Log in to continue.", "info")
            return redirect(url_for("seeker.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def _start_session(seeker_id):
    session.clear()  # new session on login prevents session fixation (and signs out any employer login)
    session["seeker_id"] = seeker_id
    session.permanent = True
    store.touch_login(seeker_id)


@bp.before_request
def _check_csrf():
    if request.method == "POST" and ac.csrf_failed():
        return ac.csrf_bounce("seeker.login")


# ------------------------------------------------------------ register --
@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_seeker():
        return redirect(url_for("seeker_dashboard"))
    errors, email, full_name = {}, "", ""
    if request.method == "POST":
        full_name = v.clean_text(request.form.get("full_name"), 80)
        email = v.normalise_email(request.form.get("email"))
        password = request.form.get("password", "")
        if len(full_name) < 2:
            errors["full_name"] = "Enter your full name."
        if err := v.validate_email(email):
            errors["email"] = err
        if err := v.validate_new_password(password):
            errors["password"] = err
        if not errors:
            try:
                if store.get_seeker_by_email(email):
                    errors["email"] = "An account with this email already exists. Log in instead."
                else:
                    auth = __import__("db").get_auth_client()
                    result = auth.auth.sign_up({"email": email, "password": password,
                                                "options": {"data": {"full_name": full_name, "role": "seeker"}}})
                    user = getattr(result, "user", None)
                    if not user:
                        errors["form"] = "Supabase did not create the account. Check your Auth settings and try again."
                    else:
                        seeker_id = store.create_seeker(email, full_name, password_hash=None)
                        # Supabase email-confirmation may mean no session is returned yet.
                        if getattr(result, "session", None):
                            _start_session(seeker_id)
                            flash(f"Welcome to NEXORA, {full_name.split()[0]}! Complete your profile to unlock job matches.", "success")
                            return redirect(url_for("seeker_dashboard"))
                        flash("Registration successful. Check your email to confirm your account, then log in.", "success")
                        return redirect(url_for("seeker.login"))
            except Exception:
                current_app.logger.exception("Supabase seeker registration failed")
                errors["form"] = "Registration could not be completed. Check your Supabase configuration and whether this email already has an Auth account."
    return render_template("auth/register.html", cfg=CFG, errors=errors, email=email, full_name=full_name,
                           google_enabled=ac.google_configured())


# --------------------------------------------------------------- login --
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_seeker():
        return redirect(url_for("seeker_dashboard"))
    next_url = safe_next(request.values.get("next"))
    errors, email = {}, ""
    if request.method == "POST":
        email = v.normalise_email(request.form.get("email"))
        password = request.form.get("password", "")
        if err := v.validate_email(email):
            errors["email"] = err
        if not password:
            errors["password"] = "Enter your password."
        if not errors:
            key = ac.lock_key("seeker", email)
            if ac.is_locked(key):
                errors["form"] = "Too many failed attempts. Try again in 15 minutes or reset your password."
            else:
                try:
                    auth = __import__("db").get_auth_client()
                    result = auth.auth.sign_in_with_password({"email": email, "password": password})
                    row = store.get_seeker_by_email(email)
                    auth_user = getattr(result, "user", None)
                    if auth_user and row:
                        ac.clear_failures(key)
                        _start_session(row["id"])
                        return redirect(next_url or url_for("seeker_dashboard"))
                    if auth_user and not row:
                        errors["form"] = "This Supabase account is not registered as a NEXORA job seeker. Please register as a job seeker first."
                    else:
                        errors["form"] = "Incorrect email or password."
                except Exception:
                    ac.record_failure(key)
                    errors["form"] = "Incorrect email or password, or email confirmation is still pending. Check your credentials and Supabase Auth settings."
    return render_template("auth/login.html", cfg=CFG, errors=errors, email=email, next_url=next_url,
                           google_enabled=ac.google_configured())


@bp.post("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "info")
    return redirect(url_for("index"))


# ------------------------------------------------------ password reset --
@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent, errors, email = False, {}, ""
    if request.method == "POST":
        email = v.normalise_email(request.form.get("email"))
        if err := v.validate_email(email):
            errors["email"] = err
        else:
            # Supabase Auth sends the reset email; keep response generic to prevent email enumeration.
            try:
                auth = __import__("db").get_auth_client()
                redirect_to = os.environ.get("SUPABASE_PASSWORD_RESET_REDIRECT_URL")
                options = {"redirect_to": redirect_to} if redirect_to else None
                if options:
                    auth.auth.reset_password_for_email(email, options=options)
                else:
                    auth.auth.reset_password_for_email(email)
            except Exception:
                current_app.logger.exception("Supabase seeker password reset request failed")
            sent = True
    return render_template("auth/forgot.html", cfg=CFG, sent=sent, errors=errors, email=email)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    try:
        data = ac.make_serializer(RESET_SALT).loads(token, max_age=ac.RESET_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return render_template("auth/reset.html", cfg=CFG, invalid=True, errors={}), 400
    row = store.get_seeker(data.get("id"))
    if not row or not hmac.compare_digest(data.get("fp", ""), ac.pw_fingerprint(row["password_hash"])):
        return render_template("auth/reset.html", cfg=CFG, invalid=True, errors={}), 400  # link already used

    errors = {}
    if request.method == "POST":
        password = request.form.get("password", "")
        if err := v.validate_new_password(password):
            errors["password"] = err
        else:
            store.update_seeker(row["id"], password_hash=generate_password_hash(password))
            flash("Password updated. Log in with your new password.", "success")
            return redirect(url_for("seeker.login"))
    return render_template("auth/reset.html", cfg=CFG, invalid=False, errors=errors, token=token)


# -------------------------------------------------------------- Google --
@bp.get("/google")
def google_start():
    if not ac.google_configured():
        flash("Google sign-in is not configured yet. Check the Supabase URL and public Auth key.", "error")
        return redirect(url_for("seeker.login"))
    try:
        target = ac.supabase_google_authorize_url(
            "seeker.google_callback", "seeker", request.args.get("next")
        )
        return redirect(target)
    except Exception:
        current_app.logger.exception("Could not start Supabase Google OAuth for seeker")
        flash("Google sign-in could not start. Check your Supabase configuration and redirect URLs.", "error")
        return redirect(url_for("seeker.login"))


@bp.get("/google/callback")
def google_callback():
    next_url = session.pop("supabase_oauth_next", "") or None
    role = session.pop("supabase_oauth_role", None)
    fail = lambda msg: (session.pop("supabase_oauth_verifier", None),
                        flash(msg, "error"), redirect(url_for("seeker.login")))[-1]  # noqa: E731

    if request.args.get("error") or request.args.get("error_description"):
        return fail("Google sign-in was cancelled or denied.")
    if role != "seeker":
        return fail("Google sign-in session expired. Please try again.")
    code = request.args.get("code", "")
    if not code:
        return fail("Supabase did not return an authorization code. Please try again.")
    try:
        user = ac.supabase_exchange_oauth_code(code)
    except Exception:
        current_app.logger.exception("Supabase Google OAuth callback failed for seeker")
        return fail("Google sign-in failed. Check the Supabase provider and redirect URL settings, then try again.")

    email = v.normalise_email(user.get("email"))
    user_metadata = user.get("user_metadata") or {}
    full_name = v.clean_text(
        user_metadata.get("full_name") or user_metadata.get("name") or
        user_metadata.get("display_name") or email.split("@")[0], 80
    ) if email else ""
    google_sub = ac.google_identity_id(user)
    if not email:
        return fail("Google did not provide an email address.")
    try:
        row = store.get_seeker_by_google_sub(google_sub) if google_sub else None
        row = row or store.get_seeker_by_email(email)
        if row:
            if google_sub and not row.get("google_sub"):
                store.update_seeker(row["id"], google_sub=google_sub)
            if full_name and not row.get("full_name"):
                store.update_seeker(row["id"], full_name=full_name)
            seeker_id = row["id"]
        else:
            seeker_id = store.create_seeker(email, full_name, password_hash=None, google_sub=google_sub)
        _start_session(seeker_id)
        return redirect(next_url or url_for("seeker_dashboard"))
    except Exception:
        current_app.logger.exception("Could not map Supabase OAuth user to a NEXORA seeker")
        return fail("Google authentication succeeded, but NEXORA could not load your job-seeker profile. Contact support.")


# ----------------------------------------------------------- demo seed --
DEMO_EMAIL = "jordan@nexora-demo.com.au"


def seed_demo(password):
    """Create (or reset) the demo job seeker used for client demos. Must run inside an app context."""
    import data

    row = store.get_seeker_by_email(DEMO_EMAIL)
    if row:
        store.update_seeker(row["id"], password_hash=generate_password_hash(password))
        return row["id"]
    sid = store.create_seeker(DEMO_EMAIL, "Jordan Reyes", password_hash=generate_password_hash(password),
                              is_demo=True)
    store.save_profile_fields(
        sid, headline="Software Developer", phone="412345678", location="Melbourne, VIC",
        education=[{"qualification": "Bachelor of Information Technology", "institution": "RMIT University",
                    "year": "2022"}],
        skills=["Python", "JavaScript", "SQL", "Django", "REST APIs", "Power BI", "Git"],
        interests=["Web applications", "Data"])
    store.save_resume(sid, "modern", "Software developer with a passion for building reliable web applications "
                                     "and turning data into useful products for customers.")
    by_title = {j["title"]: j for j in data.JOBS}
    for title, status in (("Frontend Developer", "Applied"), ("Backend Engineer", "Shortlisted"),
                          ("Senior Software Engineer", "Interview")):
        job = by_title.get(title)
        if job:
            store.add_application(sid, job["id"])
            row_app = next(a for a in store.get_applications(sid) if a["job_id"] == job["id"])
            store.set_application_status(sid, row_app["id"], status)
    for title in ("UX Designer", "Marketing Coordinator"):
        if by_title.get(title):
            store.toggle_saved(sid, by_title[title]["id"])
    return sid
