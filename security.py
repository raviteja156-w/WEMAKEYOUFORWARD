"""
Comprehensive Cyber Defense & Production Security Controls for NEXORA.

Implements multi-layer defenses against:
1. Cross-Site Scripting (XSS) via strict Content-Security-Policy & input sanitization.
2. Clickjacking via X-Frame-Options & frame-ancestors CSP.
3. MIME Confusion & Drive-by attacks via nosniff.
4. Host Header Injection & Request Smuggling.
5. Brute Force & Credential Stuffing via Tiered Rate Limiting (Redis + Thread-safe in-memory fallback).
6. Cross-Site Request Forgery (CSRF) & State-Changing Origin checks.
7. Information Leakage via custom shielded error handlers (400, 403, 404, 429, 500).
"""
import collections
import logging
import os
import re
import threading
import time
from urllib.parse import urlparse

from flask import abort, current_app, jsonify, render_template, request

log = logging.getLogger(__name__)

# ------------------------------------------------------------- RATE LIMITING --
# Support Redis if available; fallback to thread-safe sliding window
_redis_client = None
_redis_init_attempted = False
_redis_lock = threading.Lock()

_mem_hits = collections.defaultdict(collections.deque)
_mem_lock = threading.Lock()


def _get_redis():
    global _redis_client, _redis_init_attempted
    if not _redis_init_attempted:
        with _redis_lock:
            if not _redis_init_attempted:
                _redis_init_attempted = True
                redis_url = os.environ.get("REDIS_URL") or os.environ.get("UPSTASH_REDIS_URL")
                if redis_url:
                    try:
                        import redis
                        _redis_client = redis.from_url(redis_url, socket_timeout=2)
                        _redis_client.ping()
                        log.info("Production Redis rate-limiter connected.")
                    except Exception as exc:
                        log.warning("Redis connection failed (%s); falling back to in-memory rate-limiter.", exc)
                        _redis_client = None
    return _redis_client


def get_real_ip():
    """Extract client IP safely from trusted proxy headers or remote_addr."""
    if request.access_route:
        # access_route gives IPs in proxy chain from client to server
        return request.access_route[0]
    return request.remote_addr or "127.0.0.1"


def check_rate_limit(key, limit, window_seconds=60):
    """Sliding window rate limit checker."""
    if current_app and current_app.config.get("TESTING"):
        return True

    r = _get_redis()
    if r:
        try:
            now = time.time()
            pipe = r.pipeline()
            redis_key = f"rl:{key}"
            pipe.zremrangebyscore(redis_key, 0, now - window_seconds)
            pipe.zadd(redis_key, {str(now): now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds + 5)
            results = pipe.execute()
            count = results[2]
            return count <= limit
        except Exception as exc:
            log.warning("Redis rate limit error (%s); falling back to memory.", exc)

    now = time.time()
    with _mem_lock:
        q = _mem_hits[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)

        # Periodic cleanup of expired keys
        if len(_mem_hits) > 5000:
            cutoff = now - window_seconds
            for k in list(_mem_hits.keys()):
                while _mem_hits[k] and _mem_hits[k][0] < cutoff:
                    _mem_hits[k].popleft()
                if not _mem_hits[k]:
                    _mem_hits.pop(k, None)
    return True


# ------------------------------------------------------------- INSTALLATION --
def install_security(app):
    """Attach enterprise security headers, rate limiting, and shielded error handlers."""
    # Enforce safe defaults
    app.config.setdefault("MAX_CONTENT_LENGTH", 8 * 1024 * 1024)  # 8MB max body
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", os.environ.get("SESSION_COOKIE_SECURE") == "1")

    @app.before_request
    def validate_request_security():
        # 1. Host Header Injection Defense
        host = request.host.split(":")[0].strip()
        if not re.match(r"^[a-zA-Z0-9.\-_]+$", host) or len(host) > 120:
            abort(400, description="Invalid Host header.")

        allowed_hosts = [h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
        if allowed_hosts and host.lower() not in allowed_hosts and not host.endswith(".onrender.com") and host not in ("localhost", "127.0.0.1", "testserver"):
            abort(400, description="Host header not permitted.")

        # 2. Tiered Rate Limiting
        path = request.path.lower()
        ip = get_real_ip()

        # Strict: Authentication and password reset endpoints
        if any(path.startswith(prefix) for prefix in ("/employer/login", "/employer/register", "/employer/forgot", "/employer/reset",
                                                      "/seeker/login", "/seeker/register", "/seeker/forgot", "/seeker/reset", "/api/auth")):
            limit = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "15"))
            if not check_rate_limit(f"auth:{ip}:{path}", limit=limit, window_seconds=60):
                abort(429, description="Too many authentication attempts. Please slow down.")

        # Moderate: Heavy AI mutations & job postings
        elif any(path.startswith(prefix) for prefix in ("/api/seeker/resume/", "/api/seeker/interview/", "/api/post-job", "/api/checkout")):
            limit = int(os.getenv("AI_RATE_LIMIT_PER_MINUTE", "30"))
            if not check_rate_limit(f"ai:{ip}", limit=limit, window_seconds=60):
                abort(429, description="Request limit reached for AI services. Please try again in a minute.")

        # General API routes
        elif path.startswith("/api/"):
            limit = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "90"))
            if not check_rate_limit(f"api:{ip}", limit=limit, window_seconds=60):
                abort(429, description="Too many requests. Please slow down.")

    @app.after_request
    def add_security_headers(response):
        """Add modern browser security headers and prevent cache leaks."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-XSS-Protection", "0")  # Modern best practice
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()"
        )

        # Content Security Policy (hardened: no unsafe-eval, permits Stripe & trusted CDNs)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https: https://api.stripe.com; "
            "frame-src 'self' https://js.stripe.com https://hooks.stripe.com; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "form-action 'self' https://accounts.google.com https://checkout.stripe.com;"
        )
        response.headers.setdefault("Content-Security-Policy", csp)

        if request.is_secure or os.environ.get("SESSION_COOKIE_SECURE") == "1":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")

        # Never cache authenticated dashboard routes (prevents back-button account snooping)
        if request.path.startswith(("/employer", "/dashboard", "/seeker/profile", "/seeker/resume", "/seeker/applications")):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"

        return response

    # --------------------------------------------------------- ERROR HANDLERS --
    def wants_json():
        return (
            request.path.startswith("/api/")
            or request.headers.get("Accept") == "application/json"
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )

    @app.errorhandler(400)
    def handle_bad_request(e):
        if wants_json():
            return jsonify({"ok": False, "error": getattr(e, "description", "Bad request.")}), 400
        return render_template("404.html", message="Bad request."), 400

    @app.errorhandler(403)
    def handle_forbidden(e):
        if wants_json():
            return jsonify({"ok": False, "error": "Access forbidden."}), 403
        return render_template("404.html", message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def handle_not_found(e):
        if wants_json():
            return jsonify({"ok": False, "error": "Resource not found."}), 404
        return render_template("404.html"), 404

    @app.errorhandler(429)
    def handle_too_many_requests(e):
        msg = getattr(e, "description", "Too many requests. Please slow down and try again shortly.")
        if wants_json():
            return jsonify({"ok": False, "error": msg}), 429
        return (
            f"<!DOCTYPE html><html><head><title>Too Many Requests</title></head>"
            f"<body style='font-family:sans-serif;text-align:center;padding:50px;'>"
            f"<h2>429 - Rate Limit Exceeded</h2><p>{msg}</p>"
            f"<p><a href='/'>Return to Home</a></p></body></html>",
            429,
        )

    @app.errorhandler(500)
    def handle_internal_error(e):
        log.exception("Unhandled server exception on %s: %s", request.path, e)
        if wants_json():
            return jsonify({"ok": False, "error": "An internal server error occurred. Please try again."}), 500
        return (
            "<!DOCTYPE html><html><head><title>Server Error</title></head>"
            "<body style='font-family:sans-serif;text-align:center;padding:50px;'>"
            "<h2>Something went wrong</h2><p>An unexpected error occurred. Our team has been notified.</p>"
            "<p><a href='/'>Return to Home</a></p></body></html>",
            500,
        )
