"""Automated Test Suite for Task 11: Groq AI Integration, Resume Studio, Interview Engine & Alerts."""
import os
import unittest
from dotenv import load_dotenv

load_dotenv()

import app
import groq_service
import seeker_portal
import seeker_store as store
import data


class Task11IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True

    def setUp(self):
        self.client = app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["seeker_id"] = 1

    # ----------------- 1. GROQ SERVICE TESTS -----------------
    def test_groq_resume_analysis(self):
        sample_resume = "Experienced Full-Stack Developer with 4 years in Python, React, Flask, and PostgreSQL. Built scalable REST APIs."
        result = groq_service.analyze_resume_ats(sample_resume, "Full-Stack Engineer")
        self.assertIsInstance(result, dict)
        self.assertIn("ats_score", result)
        self.assertIn("points_to_increase_weightage", result)
        self.assertIn("missing_keywords", result)
        self.assertTrue(len(result["points_to_increase_weightage"]) > 0)

    def test_groq_92_ats_resume_generation(self):
        sample_resume = "Software engineer building web apps with Python and JavaScript. Handled database migrations."
        result = groq_service.generate_92_ats_resume(sample_resume, "Senior Software Engineer")
        self.assertIsInstance(result, dict)
        self.assertGreaterEqual(result.get("ats_score", 0), 92, "ATS score must be at least 92%")
        self.assertIn("professional_summary", result)
        self.assertIn("full_markdown_text", result)

    def test_groq_interview_roadmap_generation(self):
        roadmap = groq_service.generate_interview_roadmap(
            job_role="Senior Cloud Engineer",
            job_description="Architecting Kubernetes clusters on AWS",
            company_requirements="5+ years in DevOps and container orchestration",
            target_days=5
        )
        self.assertIsInstance(roadmap, dict)
        self.assertEqual(len(roadmap.get("days", [])), 5, "Must generate exactly 5 days for 5 target days")
        day_1 = roadmap["days"][0]
        self.assertIn("handwritten_note", day_1)
        self.assertIn("diagnostic_quiz", day_1)

    def test_groq_interview_qna(self):
        answer = groq_service.ask_interview_ai("System Architecture", "What is database sharding?")
        self.assertIsInstance(answer, str)
        self.assertTrue(len(answer) > 20)

    # ----------------- 2. RESUME STUDIO API TESTS -----------------
    def test_api_resume_analyze_endpoint(self):
        res = self.client.post("/api/seeker/resume/analyze", data={
            "target_role": "Backend Engineer",
            "resume_text": "Backend developer with experience in Python, FastAPI, Docker, and PostgreSQL databases."
        })
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get("ok"))
        self.assertIn("report", json_data)
        self.assertIn("ats_score", json_data["report"])

    def test_api_resume_optimize_endpoint(self):
        res = self.client.post("/api/seeker/resume/optimize-ats", json={
            "target_role": "Lead Full-Stack Engineer",
            "resume_text": "Lead developer managing microservices with React and Python."
        })
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get("ok"))
        self.assertGreaterEqual(json_data["optimized"]["ats_score"], 92)

    def test_api_resume_apply_to_profile(self):
        res = self.client.post("/api/seeker/resume/apply-to-profile", json={
            "headline": "Staff AI Engineer",
            "summary": "Proven track record architecting enterprise AI and agentic systems with 99.9% uptime.",
            "skills": ["Python", "PyTorch", "Kubernetes", "PostgreSQL", "FastAPI"]
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get("ok"))

        # Verify profile updated
        profile = store.get_profile(1)
        self.assertEqual(profile.get("headline"), "Staff AI Engineer")
        self.assertIn("Python", profile.get("skills", []))

    # ----------------- 3. INTERVIEW PRACTICE API & VIEWS -----------------
    def test_interview_practice_page_renders_200(self):
        res = self.client.get("/seeker/interview-practice")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Handwritten Study Sheet", html)
        self.assertIn("Target Interview Setup", html)
        self.assertIn("Ask AI About This Topic", html)

    def test_api_interview_generate_and_auto_sync(self):
        res = self.client.post("/api/seeker/interview/generate", json={
            "job_role": "Principal Systems Architect",
            "job_description": "Designing high-scale distributed systems and event streams.",
            "company_requirements": "Go, Python, Kafka, Kubernetes, AWS",
            "target_days": 6
        })
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get("ok"))
        self.assertEqual(len(json_data["plan"]["days"]), 6)

        # Verify auto-sync to profile headline
        profile = store.get_profile(1)
        self.assertEqual(profile.get("headline"), "Principal Systems Architect")

    def test_api_interview_ask_endpoint(self):
        res = self.client.post("/api/seeker/interview/ask", json={
            "topic": "Distributed Transactions",
            "question": "How does the Saga pattern work compared to Two-Phase Commit?"
        })
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data.get("ok"))
        self.assertIn("answer", json_data)

    # ----------------- 4. JOB ALERTS & DASHBOARD -----------------
    def test_api_alerts_save_and_dashboard_banner(self):
        res_save = self.client.post("/api/seeker/alerts/save", json={
            "keywords": "Software Engineer",
            "location": "Sydney, NSW",
            "frequency": "daily"
        })
        self.assertEqual(res_save.status_code, 200)
        self.assertTrue(res_save.get_json().get("ok"))

        # Check Seeker Dashboard reflects alert banner
        res_dash = self.client.get("/dashboard/seeker")
        self.assertEqual(res_dash.status_code, 200)
        html = res_dash.get_data(as_text=True)
        self.assertIn("Job Alert:", html)

    def test_job_matches_page_ranks_roles(self):
        res = self.client.get("/seeker/matches")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Your job matches", html)


if __name__ == "__main__":
    unittest.main()

