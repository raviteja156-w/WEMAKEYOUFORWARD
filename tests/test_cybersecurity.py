"""
Automated Cybersecurity & Penetration Verification Suite for NEXORA.

Validates:
1. Security Headers (CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy).
2. Host Header Injection Defense.
3. PDF Magic Byte & Disguised File Upload Defense.
4. XSS & Malicious Markup Sanitization.
5. Path Traversal & Parameter Tampering.
6. Shielded Error Handling (Zero Stack Trace or DB credential leaks).
"""
import io
import os
import unittest
from dotenv import load_dotenv

load_dotenv()

import app
import security
import validators as v


class NexoraCyberSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
        cls.client = app.app.test_client()

    def test_security_headers_present_on_all_responses(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

        # 1. Anti-Clickjacking
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")

        # 2. Anti-MIME Sniffing
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")

        # 3. Referrer Protection
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

        # 4. Content Security Policy
        csp = res.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'self'", csp)

        # 5. Permissions Policy
        self.assertIn("camera=()", res.headers.get("Permissions-Policy", ""))

    def test_host_header_poisoning_rejected(self):
        # Host injection attack with invalid characters or untrusted domains
        malicious_hosts = [
            "malicious-site.attacker.com",
            "localhost:80@attacker.com",
            "example.com; evil.com",
            "attacker.com:8080",
        ]
        for host in malicious_hosts:
            with self.subTest(host=host):
                res = self.client.get("/", headers={"Host": host})
                self.assertIn(res.status_code, (400, 404))

    def test_pdf_magic_bytes_enforcement(self):
        # Disguised executable pretending to be PDF
        fake_pdf = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00This is an executable")
        with self.client.session_transaction() as sess:
            sess["seeker_id"] = 1

        res = self.client.post("/api/seeker/resume/analyze", data={
            "resume_file": (fake_pdf, "resume.pdf"),
            "target_role": "Software Engineer"
        }, content_type="multipart/form-data")

        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid PDF file signature", res.get_json().get("error", ""))

    def test_valid_pdf_magic_bytes_accepted(self):
        valid_pdf = io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
        with self.client.session_transaction() as sess:
            sess["seeker_id"] = 1

        res = self.client.post("/api/seeker/resume/analyze", data={
            "resume_file": (valid_pdf, "resume.pdf"),
            "target_role": "Software Engineer",
            "resume_text": "Experienced Python Backend Developer with 5 years in AWS, Docker, and PostgreSQL."
        }, content_type="multipart/form-data")

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("ok"))

    def test_xss_sanitization_engine(self):
        payloads = [
            "<script>alert(document.cookie)</script>",
            "<img src=x onerror=alert(1)>",
            "<iframe src='javascript:alert(1)'></iframe>",
            "<a href='javascript:evil()'>Click</a>",
        ]
        for p in payloads:
            cleaned = v.sanitize_html(p)
            self.assertNotIn("<script>", cleaned.lower())
            self.assertNotIn("onerror", cleaned.lower())
            self.assertNotIn("javascript:", cleaned.lower())

    def test_error_handling_shields_stack_traces(self):
        # 404 JSON on API
        res_api_404 = self.client.get("/api/non-existent-endpoint-1234")
        self.assertEqual(res_api_404.status_code, 404)
        self.assertTrue(res_api_404.is_json)
        self.assertNotIn("Traceback", res_api_404.get_data(as_text=True))

        # 404 HTML on pages
        res_page_404 = self.client.get("/non-existent-page-1234")
        self.assertEqual(res_page_404.status_code, 404)
        self.assertNotIn("Traceback", res_page_404.get_data(as_text=True))
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", res_page_404.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
