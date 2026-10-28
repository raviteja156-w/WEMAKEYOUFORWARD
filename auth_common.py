"""
Role-agnostic authentication helpers shared by the employer and job-seeker flows:
CSRF, safe redirects, login rate-limiting, reset tokens, email sending and Google OAuth.
"""
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from flask import current_app, flash, redirect, request, session, url_for
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

# ------------------------------------------------------------------ CSRF --
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def csrf_failed():
    """True when a POST form is missing/has a wrong CSRF token."""
    sent = request.form.get("csrf_token", "")
    return not sent or not hmac.compare_digest(sent, session.get("_csrf", ""))


def csrf_bounce(fallback_endpoint):
    flash("Your session expired. Please try again.", "error")
    return redirect(request.referrer or url_for(fallback_endpoint))


# -------------------------------------------------------------- redirects --
def safe_next(target):
    """Only allow same-site relative redirects (blocks open-redirect attacks)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def wants_json():
    return request.path.startswith("/api/")


# --------------------------------------------------------- login throttling --
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60
# Used to spend the same time hashing when an email doesn't exist (prevents timing leaks).
DUMMY_HASH = generate_password_hash("nexora-dummy-password")
# In-memory tracker. Fine for a single worker (see render.yaml); use Redis if you scale out.
failed_logins = {}


def lock_key(scope, email):
    return f"{scope}|{request.remote_addr}|{email}"


def is_locked(key):
    now = time.time()
    attempts = [t for t in failed_logins.get(key, []) if now - t < LOCKOUT_SECONDS]
    failed_logins[key] = attempts
    return len(attempts) >= MAX_FAILED_LOGINS


def record_failure(key):
    failed_logins.setdefault(key, []).append(time.time())
    if len(failed_logins) > 5000:  # keep memory bounded
        now = time.time()
        for k in [k for k, ts in failed_logins.items() if not any(now - t < LOCKOUT_SECONDS for t in ts)]:
            failed_logins.pop(k, None)


def clear_failures(key):
    failed_logins.pop(key, None)


# ----------------------------------------------------------- reset tokens --
RESET_TOKEN_MAX_AGE = 60 * 60  # 1 hour


def make_serializer(salt):
    return URLSafeTimedSerializer(current_app.secret_key, salt=salt)


def pw_fingerprint(password_hash):
    """Ties a reset link to the current password so it dies once used."""
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


def send_email(to, subject, body):
    host = os.environ.get("SMTP_HOST")
    if not host:
        current_app.logger.warning("SMTP not configured. Email to %s:\n%s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM", "NEXORA <no-reply@nexora.com.au>")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=10) as smtp:
            smtp.starttls()
            if os.environ.get("SMTP_USER"):
                smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            smtp.send_message(msg)
    except Exception:  # never reveal mail failures to the visitor
        current_app.logger.exception("Failed to send email to %s", to)


# -------------------------------------------------------- Supabase Google OAuth --
# OAuth is handled by Supabase Auth. Google Client ID/Secret belong in the
# Supabase dashboard, not in this Flask application's environment.
import base64


def google_configured():
    """True when the app has the public Supabase settings needed to start OAuth."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_ANON_KEY") or
           os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    return bool(url and key and "YOUR_PROJECT_REF" not in url and
                "REPLACE_WITH" not in key and not key.startswith("sb_secret_"))


def _supabase_public_config():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_ANON_KEY") or
           os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()
    if not url or not key or "YOUR_PROJECT_REF" in url or "REPLACE_WITH" in key:
        raise RuntimeError(
            "Supabase Google OAuth is not configured. Set SUPABASE_URL and "
            "SUPABASE_ANON_KEY (or SUPABASE_PUBLISHABLE_KEY) in .env."
        )
    if key.startswith("sb_secret_"):
        raise RuntimeError("Use the public Supabase anon/publishable key for Auth, not a secret key.")
    return url, key


def supabase_google_authorize_url(callback_endpoint, role, next_url=None):
    """Create a Supabase-hosted Google OAuth URL using PKCE and store verifier in session."""
    url, _key = _supabase_public_config()
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    callback_url = url_for(callback_endpoint, _external=True)
    session["supabase_oauth_verifier"] = verifier
    session["supabase_oauth_role"] = role
    session["supabase_oauth_next"] = safe_next(next_url) or ""
    params = {
        "provider": "google",
        "redirect_to": callback_url,
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    }
    return f"{url}/auth/v1/authorize?{urllib.parse.urlencode(params)}"


def supabase_exchange_oauth_code(code):
    """Exchange the code returned by Supabase for a Supabase Auth user/session."""
    url, key = _supabase_public_config()
    verifier = session.get("supabase_oauth_verifier")
    if not verifier or not code:
        raise ValueError("OAuth session expired. Start Google sign-in again.")
    # Supabase GoTrue's PKCE exchange expects a JSON body, not form-encoded data.
    payload = json.dumps({
        "auth_code": code,
        "code_verifier": verifier,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/auth/v1/token?grant_type=pkce",
        data=payload,
        headers={
            "apikey": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        result = _http_json(req)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase OAuth code exchange failed (HTTP {exc.code}): {details[:500]}") from exc
    user = result.get("user")
    if not isinstance(user, dict) or not user.get("email"):
        raise ValueError("Supabase did not return a user with an email address.")
    # Clear the PKCE verifier after a successful exchange; callback consumes role/next too.
    session.pop("supabase_oauth_verifier", None)
    return user


def google_identity_id(user):
    """Return the Google provider subject when Supabase includes it."""
    for identity in (user.get("identities") or []):
        if identity.get("provider") == "google":
            data = identity.get("identity_data") or {}
            return identity.get("provider_id") or data.get("sub") or identity.get("id")
    return None


def _http_json(req):
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))
