"""
Employer authentication and onboarding.

Routes (all under /employer):
    GET/POST  /register        Create an employer account
    GET/POST  /login           Sign in
    POST      /logout          Sign out
    GET/POST  /setup           Company profile (first-time setup and later edits)
    GET/POST  /forgot          Request a password-reset link
    GET/POST  /reset/<token>   Choose a new password
    GET       /google          Start "Continue with Google"
    GET       /google/callback Finish "Continue with Google"
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
import db
import validators as v
from auth_common import csrf_token, safe_next  # noqa: F401  (csrf_token is exported to templates)

bp = Blueprint("employer", __name__, url_prefix="/employer")

RESET_SALT = "employer-password-reset"

# Text + routing used by the shared templates in templates/auth/
CFG = {
    "bp": "employer",
    "page_label": "Employer",
    "ask_name": False,
    "register_title": "Create employer account",
    "register_sub": "Join thousands of Australian employers hiring great talent.",
    "login_page_title": "Employer login",
    "login_sub": "Sign in to manage your jobs, candidates and company profile.",
    "other_bp": "seeker",
    "other_prompt": "Looking for a job?",
    "other_label": "Create a job seeker account",
    "other_login_label": "Job seeker login",
    # Employer registration uses email/password only; Google is offered on login.
    "show_google_register": False,
}


# ------------------------------------------------------------- helpers --
def current_employer():
    """The signed-in employer row, or None. Cached for the request."""
    if "employer" not in g:
        g.employer = db.get_employer(session.get("employer_id"))
        if g.employer is None:
            session.pop("employer_id", None)
    return g.employer


def current_company():
    emp = current_employer()
    if not emp:
        return None
    if "company" not in g:
        comp = db.get_company(emp["id"])
        if comp:
            meta = session.get(f"company_meta_{emp['id']}", {})
            comp = {**comp, **meta}
        g.company = comp
    return g.company


def employer_login_required(view):
    """Require a signed-in employer (company setup may still be incomplete)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_employer():
            if ac.wants_json():
                return jsonify({"ok": False, "error": "Please log in."}), 401
            flash("Log in to continue.", "info")
            return redirect(url_for("employer.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def employer_required(view):
    """Require a signed-in employer who has finished company setup."""
    @wraps(view)
    @employer_login_required
    def wrapped(*args, **kwargs):
        if not current_employer()["onboarding_complete"]:
            if ac.wants_json():
                return jsonify({"ok": False, "error": "Complete your company profile first."}), 403
            return redirect(url_for("employer.setup", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def _start_session(employer_id):
    session.clear()  # new session on login prevents session fixation
    session["employer_id"] = employer_id
    session.permanent = True
    db.touch_login(employer_id)


def _after_login(emp, next_url):
    if not emp["onboarding_complete"]:
        return redirect(url_for("employer.setup", next=next_url) if next_url else url_for("employer.setup"))
    return redirect(next_url or url_for("employer_dashboard"))


@bp.before_request
def _check_csrf():
    if request.method == "POST" and ac.csrf_failed():
        return ac.csrf_bounce("employer.login")


# ------------------------------------------------------------ register --
@bp.route("/register", methods=["GET", "POST"])
def register():
    """Create a Supabase Auth employer and send confirmation links to employer login."""
    if current_employer():
        return _after_login(current_employer(), None)

    errors, email = {}, ""
    if request.method == "POST":
        email = v.normalise_email(request.form.get("email"))
        password = request.form.get("password", "")

        if err := v.validate_email(email):
            errors["email"] = err
        if err := v.validate_new_password(password):
            errors["password"] = err

        if not errors:
            try:
                # Do not create another employer record for an email already registered
                # in the NEXORA employer table.
                if db.get_employer_by_email(email):
                    errors["email"] = "An employer account with this email already exists. Log in instead."
                else:
                    auth = db.get_auth_client()
                    redirect_to = (
                        os.environ.get("SUPABASE_EMPLOYER_CONFIRM_REDIRECT_URL", "").strip()
                        or url_for("employer.login", _external=True)
                    )
                    result = auth.auth.sign_up({
                        "email": email,
                        "password": password,
                        "options": {
                            "data": {"role": "employer"},
                            "email_redirect_to": redirect_to,
                        },
                    })
                    user = getattr(result, "user", None)
                    if not user:
                        errors["form"] = "Supabase did not create the account. Check Auth settings and try again."
                    elif getattr(user, "identities", None) == []:
                        # Supabase may return an obfuscated user for an existing Auth email.
                        errors["email"] = "An account with this email may already exist. Try logging in."
                    else:
                        # Create the matching application record so login can identify
                        # this account as an employer. Profile details are collected later.
                        db.create_employer(email, password_hash=None, onboarding_complete=False)
                        flash(
                            "Registration successful. Check your email to confirm your account, "
                            "then return here and log in.",
                            "success",
                        )
                        return redirect(url_for("employer.login"))
            except Exception:
                current_app.logger.exception("Supabase employer registration failed")
                errors["form"] = (
                    "Registration could not be completed. The email may already be registered, "
                    "or Supabase/database configuration needs checking."
                )

    return render_template(
        "auth/register.html", cfg=CFG, errors=errors, email=email, full_name="",
        google_enabled=ac.google_configured(),
    )


# --------------------------------------------------------------- login --
@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = safe_next(request.values.get("next"))
    existing_employer = current_employer()
    if existing_employer:
        # Even an already signed-in employer must complete setup before dashboard access.
        return _after_login(existing_employer, next_url)
    errors, email = {}, ""
    if request.method == "POST":
        email = v.normalise_email(request.form.get("email"))
        password = request.form.get("password", "")
        if err := v.validate_email(email):
            errors["email"] = err
        if not password:
            errors["password"] = "Enter your password."
        if not errors:
            key = ac.lock_key("employer", email)
            if ac.is_locked(key):
                errors["form"] = "Too many failed attempts. Try again in 15 minutes or reset your password."
            else:
                emp = db.get_employer_by_email(email)
                try:
                    auth = db.get_auth_client()
                    result = auth.auth.sign_in_with_password({"email": email, "password": password})
                    auth_user = getattr(result, "user", None)
                    if auth_user:
                        if not emp:
                            try:
                                employer_id = db.create_employer(email, password_hash=None, onboarding_complete=False)
                                emp = db.get_employer(employer_id)
                            except Exception:
                                emp = db.get_employer_by_email(email)
                        if emp:
                            ac.clear_failures(key)
                            _start_session(emp["id"])
                            return _after_login(emp, next_url)
                    errors["form"] = "Incorrect email or password."
                except Exception:
                    ac.record_failure(key)
                    errors["form"] = "Incorrect email or password, or email confirmation is still pending."
    return render_template("auth/login.html", cfg=CFG, errors=errors, email=email, next_url=next_url,
                           google_enabled=ac.google_configured())


@bp.post("/logout")
def logout():
    session.clear()
    flash("You've been signed out.", "info")
    return redirect(url_for("index"))


# --------------------------------------------------------------- setup --
@bp.route("/setup", methods=["GET", "POST"])
@bp.route("/profile", methods=["GET", "POST"])
@employer_login_required
def setup():
    emp = current_employer()
    existing = db.get_company(emp["id"])
    editing = bool(emp["onboarding_complete"])
    show_overview = editing and request.args.get("edit") != "1"
    next_url = safe_next(request.values.get("next"))
    errors = {}

    if request.method == "POST":
        form = request.form
        c_name = v.clean_text(form.get("company_name"), 100)
        c_contact = v.clean_text(form.get("contact_name"), 100)
        parts = c_contact.split() if c_contact else []
        c_first = parts[0] if parts else (v.clean_text(form.get("contact_first"), 50) or "Recruiter")
        c_last = " ".join(parts[1:]) if len(parts) > 1 else (v.clean_text(form.get("contact_last"), 50) or "Contact")

        f = {
            "name": c_name,
            "country": form.get("country", "AU"),
            "registered_name": v.clean_text(form.get("registered_name") or c_name, 150),
            "is_registered": form.get("is_registered", "yes") == "yes",
            "abn": v.digits_only(form.get("abn")),
            "contact_first": c_first,
            "contact_last": c_last,
            "phone_country": form.get("phone_country", "AU"),
            "phone": form.get("phone", ""),
        }
        if len(f["name"]) < 2:
            errors["company_name"] = "Enter your company name."
        if f["country"] not in v.COUNTRY_BY_CODE:
            errors["country"] = "Choose a country."
        if len(f["registered_name"]) < 2:
            f["registered_name"] = f["name"]
        if f["is_registered"] and f["abn"] and not v.is_valid_abn(f["abn"]):
            errors["abn"] = "That ABN doesn't look right. Check the 11 digits and try again."
        if not f["is_registered"]:
            f["abn"] = ""
        if not f["contact_first"]:
            f["contact_first"] = "Recruiter"
        if not f["contact_last"]:
            f["contact_last"] = "Contact"
        if f["phone_country"] not in v.COUNTRY_BY_CODE:
            f["phone_country"] = "AU"
        if f["phone"]:
            digits, err = v.normalise_phone(f["phone_country"], f["phone"])
            if not err:
                f["phone"] = digits

        meta = {
            "website": form.get("website", "").strip(),
            "industry": form.get("industry", "Information Technology (IT)").strip(),
            "company_size": form.get("company_size", "11 - 50 employees").strip(),
            "location": form.get("location", "Sydney, NSW").strip(),
            "logo_url": form.get("logo_url", "").strip(),
            "contact_name": c_contact or f"{f['contact_first']} {f['contact_last']}".strip(),
            "work_email": form.get("work_email", "").strip(),
            "job_roles": form.get("job_roles", "").strip(),
            "preferred_locations": form.get("preferred_locations", "").strip(),
            "employment_types": form.get("employment_types", "").strip(),
            "work_arrangements": form.get("work_arrangements", "").strip(),
        }
        session[f"company_meta_{emp['id']}"] = meta

        if not errors:
            db.save_company(emp["id"], {**f, "is_registered": int(f["is_registered"])})
            flash("Company profile saved." if editing else "You're all set. Welcome to NEXORA.", "success")
            return redirect(next_url or url_for("employer_dashboard"))
        values = {**f, **meta, "phone": form.get("phone", ""), "abn": form.get("abn", "")}
    else:
        meta = session.get(f"company_meta_{emp['id']}", {})
        contact_full = meta.get("contact_name")
        if not contact_full and existing:
            contact_full = f"{existing.get('contact_first', '')} {existing.get('contact_last', '')}".strip()
        values = {
            "name": existing["name"] if existing else "",
            "country": existing["country"] if existing else "AU",
            "registered_name": existing["registered_name"] if existing else "",
            "is_registered": bool(existing["is_registered"]) if existing else True,
            "abn": v.format_abn(existing["abn"]) if existing and existing["abn"] else "",
            "contact_first": existing["contact_first"] if existing else "",
            "contact_last": existing["contact_last"] if existing else "",
            "phone_country": existing["phone_country"] if existing else "AU",
            "phone": existing["phone"] if existing else "",
            "website": meta.get("website", ""),
            "industry": meta.get("industry", "Information Technology (IT)"),
            "company_size": meta.get("company_size", "11 - 50 employees"),
            "location": meta.get("location", "Sydney, NSW"),
            "logo_url": meta.get("logo_url", ""),
            "contact_name": contact_full or "",
            "work_email": meta.get("work_email", emp.get("email", "")),
            "job_roles": meta.get("job_roles", "Software Engineer, Data Analyst, DevOps Engineer, UI/UX Designer"),
            "preferred_locations": meta.get("preferred_locations", "Sydney, NSW, Melbourne, VIC, Brisbane, QLD"),
            "employment_types": meta.get("employment_types", "Full-time, Part-time, Contract, Internship"),
            "work_arrangements": meta.get("work_arrangements", "On-site, Hybrid, Remote"),
        }
    return render_template("employer/setup.html", errors=errors, values=values, editing=editing,
                           show_overview=show_overview, next_url=next_url, countries=v.COUNTRIES,
                           company=current_company())


# ------------------------------------------------------ password reset --
@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent, errors, email = False, {}, ""
    if request.method == "POST":
        email = v.normalise_email(request.form.get("email"))
        if err := v.validate_email(email):
            errors["email"] = err
        else:
            # Employer accounts are provisioned by an administrator; Supabase handles reset email.
            try:
                auth = db.get_auth_client()
                redirect_to = os.environ.get("SUPABASE_PASSWORD_RESET_REDIRECT_URL")
                options = {"redirect_to": redirect_to} if redirect_to else None
                if options:
                    auth.auth.reset_password_for_email(email, options=options)
                else:
                    auth.auth.reset_password_for_email(email)
            except Exception:
                current_app.logger.exception("Supabase employer password reset request failed")
            sent = True  # same response whether or not the account exists
    return render_template("auth/forgot.html", cfg=CFG, sent=sent, errors=errors, email=email)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    try:
        data = ac.make_serializer(RESET_SALT).loads(token, max_age=ac.RESET_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return render_template("auth/reset.html", cfg=CFG, invalid=True, errors={}), 400
    emp = db.get_employer(data.get("id"))
    if not emp or not hmac.compare_digest(data.get("fp", ""), ac.pw_fingerprint(emp["password_hash"])):
        return render_template("auth/reset.html", cfg=CFG, invalid=True, errors={}), 400  # link already used

    errors = {}
    if request.method == "POST":
        password = request.form.get("password", "")
        if err := v.validate_new_password(password):
            errors["password"] = err
        else:
            db.update_employer(emp["id"], password_hash=generate_password_hash(password))
            flash("Password updated. Log in with your new password.", "success")
            return redirect(url_for("employer.login"))
    return render_template("auth/reset.html", cfg=CFG, invalid=False, errors=errors, token=token)


# -------------------------------------------------------------- Google --
@bp.get("/google")
def google_start():
    if not ac.google_configured():
        flash("Google sign-in is not configured yet. Check the Supabase URL and public Auth key.", "error")
        return redirect(url_for("employer.login"))
    try:
        target = ac.supabase_google_authorize_url(
            "employer.google_callback", "employer", request.args.get("next")
        )
        return redirect(target)
    except Exception:
        current_app.logger.exception("Could not start Supabase Google OAuth for employer")
        flash("Google sign-in could not start. Check your Supabase configuration and redirect URLs.", "error")
        return redirect(url_for("employer.login"))


@bp.get("/google/callback")
def google_callback():
    next_url = session.pop("supabase_oauth_next", "") or None
    role = session.pop("supabase_oauth_role", None)
    fail = lambda msg: (session.pop("supabase_oauth_verifier", None),
                        flash(msg, "error"), redirect(url_for("employer.login")))[-1]  # noqa: E731

    if request.args.get("error") or request.args.get("error_description"):
        return fail("Google sign-in was cancelled or denied.")
    if role != "employer":
        return fail("Google sign-in session expired. Please try again.")
    code = request.args.get("code", "")
    if not code:
        return fail("Supabase did not return an authorization code. Please try again.")
    try:
        user = ac.supabase_exchange_oauth_code(code)
    except Exception:
        current_app.logger.exception("Supabase Google OAuth callback failed for employer")
        return fail("Google sign-in failed. Check the Supabase provider and redirect URL settings, then try again.")

    email = v.normalise_email(user.get("email"))
    google_sub = ac.google_identity_id(user)
    if not email:
        return fail("Google did not provide an email address.")
    try:
        emp = db.get_employer_by_google_sub(google_sub) if google_sub else None
        emp = emp or db.get_employer_by_email(email)
        if emp:
            if google_sub and not emp.get("google_sub"):
                db.update_employer(emp["id"], google_sub=google_sub)
            employer_id = emp["id"]
        else:
            employer_id = db.create_employer(email, google_sub=google_sub, onboarding_complete=False)
        _start_session(employer_id)
        return _after_login(db.get_employer(employer_id), next_url)
    except Exception:
        current_app.logger.exception("Could not map Supabase OAuth user to a NEXORA employer")
        return fail("Google authentication succeeded, but NEXORA could not load your employer profile. Contact support.")


# ----------------------------------------------------------- demo seed --
DEMO_EMAIL = "demo@northlane.com.au"


def seed_demo(password):
    """Create (or reset) the Northlane Digital demo account used for client demos."""
    emp = db.get_employer_by_email(DEMO_EMAIL)
    if emp:
        db.update_employer(emp["id"], password_hash=generate_password_hash(password))
        return emp["id"]
    employer_id = db.create_employer(DEMO_EMAIL, password_hash=generate_password_hash(password),
                                     is_demo=True)
    db.save_company(employer_id, {
        "name": "Northlane Digital", "country": "AU", "registered_name": "Northlane Digital Pty Ltd",
        "is_registered": 1, "abn": "51824753556", "contact_first": "Sam", "contact_last": "Carter",
        "phone_country": "AU", "phone": "412345678",
    })
    return employer_id
