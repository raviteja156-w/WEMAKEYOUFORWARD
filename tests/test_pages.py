"""Automated route and page smoke tests for NEXORA."""
import os
import unittest
from dotenv import load_dotenv

load_dotenv()
import app


class NexoraPageSmokeTests(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

    def test_public_pages_return_200(self):
        pages = [
            "/",
            "/jobs",
            "/jobs/1000",
            "/companies",
            "/companies/northlane-digital",
            "/pricing",
            "/employer/login",
            "/employer/register",
            "/employer/forgot",
            "/seeker/login",
            "/seeker/register",
            "/seeker/forgot",
            "/admin/login",
            "/privacy",
            "/terms",
        ]
        for url in pages:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200, f"Page {url} returned {res.status_code}")

    def test_unauthenticated_protected_routes_redirect(self):
        # Admin protected route
        res_admin = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(res_admin.status_code, 302)
        self.assertIn("/admin/login", res_admin.headers.get("Location", ""))

        protected_employer = ["/dashboard/employer", "/post-job", "/checkout", "/applicants", "/employer/setup"]
        for url in protected_employer:
            with self.subTest(url=url):
                client = app.app.test_client()
                res = client.get(url, follow_redirects=False)
                self.assertEqual(res.status_code, 302)
                self.assertIn("/employer/login", res.headers.get("Location", ""))

        protected_seeker = [
            "/dashboard/seeker", "/seeker/profile", "/seeker/resume",
            "/seeker/applications", "/seeker/matches", "/seeker/upgrade",
            "/seeker/saved", "/seeker/interview-practice", "/seeker/alerts"
        ]
        for url in protected_seeker:
            with self.subTest(url=url):
                client = app.app.test_client()
                res = client.get(url, follow_redirects=False)
                self.assertEqual(res.status_code, 302)
                self.assertIn("/seeker/login", res.headers.get("Location", ""))

    def test_authenticated_seeker_pages_return_200(self):
        with self.client.session_transaction() as sess:
            sess["seeker_id"] = 1

        seeker_pages = [
            "/dashboard/seeker", "/seeker/profile", "/seeker/resume",
            "/seeker/applications", "/seeker/matches", "/seeker/upgrade",
            "/seeker/saved", "/seeker/interview-practice", "/seeker/alerts"
        ]
        for url in seeker_pages:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200, f"Seeker page {url} returned {res.status_code}")

    def test_authenticated_employer_pages_return_200(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["employer_id"] = 1

        employer_pages = ["/dashboard/employer", "/post-job", "/checkout", "/applicants", "/employer/setup"]
        for url in employer_pages:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200, f"Employer page {url} returned {res.status_code}")

    def test_authenticated_admin_page_returns_200(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["is_admin"] = True
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)

    def test_404_page(self):
        res = self.client.get("/non-existent-random-page")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
