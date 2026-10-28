"""Additional baseline security controls for NEXORA Flask."""
from collections import defaultdict, deque
from functools import wraps
import os
import time
from flask import abort, request, current_app

_hits = defaultdict(deque)

def install_security(app):
    # Restrict request body size, protect cookies and disable JSON key sorting surprises.
    app.config.setdefault("MAX_CONTENT_LENGTH", 2 * 1024 * 1024)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("WTF_CSRF_ENABLED", True)

    @app.before_request
    def basic_rate_limit():
        # Conservative per-IP request limit for authentication and mutation endpoints.
        path = request.path.lower()
        if path.startswith(("/auth", "/login", "/register", "/api/auth", "/seeker", "/employer")):
            now = time.time()
            key = (request.remote_addr or "unknown", path)
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "60")):
                abort(429)
            q.append(now)
            if len(_hits) > 10000:
                cutoff = now - 60
                for k in list(_hits):
                    while _hits[k] and _hits[k][0] < cutoff:
                        _hits[k].popleft()
                    if not _hits[k]:
                        _hits.pop(k, None)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy",
            "default-src 'self' https: data:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
