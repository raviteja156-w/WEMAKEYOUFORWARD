"""
NEXORA reference data + the sample job board used to seed Supabase on first run.

Jobs, employer applicants, job orders and admin reports now live in Supabase (see job_store.py).
The lists below are fixed options (locations, industries, packages...) and the one-time seed data.
"""
import itertools
from datetime import date, timedelta

_id_counter = itertools.count(1000)


def next_id():
    return next(_id_counter)


LOCATIONS = [
    "Sydney, NSW", "Melbourne, VIC", "Brisbane, QLD", "Perth, WA",
    "Adelaide, SA", "Canberra, ACT", "Hobart, TAS", "Darwin, NT",
]

INDUSTRIES = [
    "Technology", "Healthcare", "Construction", "Retail", "Finance",
    "Marketing", "Logistics", "Design", "Trades & Services", "Education",
]

JOB_TYPES = ["Full-time", "Part-time", "Casual", "Contract", "Internship"]
WORK_MODES = ["On-site", "Hybrid", "Remote"]
EXPERIENCE_LEVELS = ["Entry level", "1-3 years", "3-5 years", "5+ years", "Manager"]

COMPANIES = [
    ("Northlane Digital", "ND", "#5D4FE0"),
    ("Harbourfield Health", "HH", "#2DD9B8"),
    ("Ferro & Cole Construction", "FC", "#0B1230"),
    ("Bright Retail Co.", "BR", "#E0975D"),
    ("Meridian Capital", "MC", "#5D4FE0"),
    ("Compass Marketing Studio", "CM", "#2DD9B8"),
    ("Southwind Logistics", "SL", "#0B1230"),
    ("Studio Fenwick", "SF", "#E0975D"),
    ("Ampere Trades Group", "AT", "#5D4FE0"),
    ("Lumen Learning", "LL", "#2DD9B8"),
    ("Ridgeline Analytics", "RA", "#0B1230"),
    ("Coastal Care Health", "CC", "#E0975D"),
]

_JOB_SEED = [
    ("Senior Software Engineer", "Technology", ["Python", "React", "AWS"], 130000, 165000),
    ("Product Designer", "Design", ["Figma", "UX Research", "Prototyping"], 100000, 125000),
    ("Frontend Developer", "Technology", ["JavaScript", "React", "CSS"], 90000, 115000),
    ("Marketing Coordinator", "Marketing", ["Content", "SEO", "Campaigns"], 65000, 78000),
    ("Registered Nurse", "Healthcare", ["Patient Care", "Clinical", "AHPRA"], 78000, 96000),
    ("Construction Project Manager", "Construction", ["Scheduling", "Budgeting", "Safety"], 120000, 150000),
    ("Retail Supervisor", "Retail", ["Team Leadership", "POS", "Customer Service"], 58000, 66000),
    ("Data Analyst", "Technology", ["SQL", "Power BI", "Python"], 85000, 105000),
    ("Customer Support Specialist", "Technology", ["Zendesk", "Communication", "Troubleshooting"], 60000, 70000),
    ("Electrician", "Trades & Services", ["Licensed", "Residential", "Fault-finding"], 75000, 98000),
    ("Digital Marketing Specialist", "Marketing", ["SEM", "Analytics", "Social"], 75000, 92000),
    ("Warehouse Team Leader", "Logistics", ["Inventory", "WHS", "Forklift Licence"], 62000, 74000),
    ("Financial Analyst", "Finance", ["Modelling", "Excel", "Reporting"], 95000, 118000),
    ("UX Designer", "Design", ["Wireframing", "User Testing", "Figma"], 95000, 120000),
    ("Project Coordinator", "Construction", ["Documentation", "Scheduling", "Stakeholders"], 70000, 85000),
    ("Backend Engineer", "Technology", ["Node.js", "PostgreSQL", "Docker"], 120000, 150000),
    ("Sales Development Representative", "Marketing", ["Prospecting", "CRM", "Outreach"], 65000, 85000),
    ("Aged Care Worker", "Healthcare", ["Certificate III", "Compassionate Care", "First Aid"], 55000, 64000),
    ("Site Supervisor", "Construction", ["OH&S", "Trade Coordination", "Reporting"], 90000, 112000),
    ("HR Business Partner", "Finance", ["Employee Relations", "Recruitment", "Policy"], 100000, 122000),
    ("Graphic Designer", "Design", ["Adobe Suite", "Branding", "Typography"], 68000, 82000),
    ("Civil Engineer", "Construction", ["AutoCAD", "Structural Design", "Compliance"], 95000, 118000),
    ("Software Developer", "Technology", ["Python", "JavaScript", "SQL"], 95000, 120000),
    ("Python Developer", "Technology", ["Python", "Django", "REST APIs"], 100000, 125000),
]

def _build_jobs():
    jobs = []
    for i, (title, industry, tags, smin, smax) in enumerate(_JOB_SEED):
        company, initials, color = COMPANIES[i % len(COMPANIES)]
        location = LOCATIONS[i % len(LOCATIONS)]
        jtype = JOB_TYPES[i % len(JOB_TYPES)]
        mode = WORK_MODES[i % len(WORK_MODES)]
        exp = EXPERIENCE_LEVELS[i % len(EXPERIENCE_LEVELS)]
        posted_days_ago = (i * 3) % 21
        featured = i % 5 == 0
        urgent = i % 7 == 0
        jobs.append({
            "id": next_id(),
            "title": title,
            "company": company,
            "company_initials": initials,
            "company_color": color,
            "location": location,
            "type": jtype,
            "mode": mode,
            "experience": exp,
            "industry": industry,
            "salary_min": smin,
            "salary_max": smax,
            "tags": tags,
            "posted_days_ago": posted_days_ago,
            "closing_date": (date.today() + timedelta(days=30 - posted_days_ago)).isoformat(),
            "featured": featured,
            "urgent": urgent,
            "status": "Approved",
            "views": 120 + i * 17,
            "applications_count": 4 + (i * 3) % 40,
            "about_role": (
                f"We're looking for a {title.lower()} to join {company}'s growing team in "
                f"{location.split(',')[0]}. You'll work closely with cross-functional teams to "
                f"deliver high-impact outcomes in {industry.lower()}."
            ),
            "responsibilities": [
                "Own key deliverables from planning through to delivery",
                "Collaborate with stakeholders across the business",
                "Bring a continuous-improvement mindset to everyday work",
                "Mentor junior team members where relevant",
            ],
            "requirements": [
                f"Experience level: {exp}",
                f"Strong skills in {', '.join(tags)}",
                "Excellent communication and collaboration skills",
                "Right to work in Australia",
            ],
            "benefits": [
                "Flexible working arrangements",
                "Career development budget",
                "Health & wellbeing program",
                "Generous parental leave",
            ],
            "about_company": (
                f"{company} is a {industry.lower()} company built on the idea that great "
                f"work happens when people are set up to do their best work."
            ),
        })
    return jobs


# A few sample jobs start as "Pending" so the admin moderation queue has something to review.
_PENDING_SEED = (1, 9, 17)


def build_seed_jobs():
    """Sample job board copied into Supabase once (job_store.seed_demo_jobs). Ids start at 1000."""
    global _id_counter
    _id_counter = itertools.count(1000)
    jobs = _build_jobs()
    for idx in _PENDING_SEED:
        if idx < len(jobs):
            jobs[idx]["status"] = "Pending"
    return jobs


DEMO_REPORTS = [
    {"id": 1, "type": "Job listing", "reason": "Misleading salary range",
     "target": "Retail Supervisor — Bright Retail Co.", "status": "Open"},
    {"id": 2, "type": "Employer", "reason": "Duplicate company profile",
     "target": "Southwind Logistics", "status": "Open"},
    {"id": 3, "type": "Job listing", "reason": "Suspicious contact request",
     "target": "Data Analyst — Ridgeline Analytics", "status": "Resolved"},
]

PACKAGES = [
    {"id": "basic", "name": "Basic", "price": 19, "tagline": "Get listed and discovered.",
     "features": ["Standard listing", "30 days live", "Basic analytics"]},
    {"id": "featured", "name": "Featured", "price": 39, "tagline": "Stand out in search results.",
     "features": ["Priority placement", "30 days live", "Featured badge", "Full analytics"]},
    {"id": "urgent", "name": "Urgent", "price": 69, "tagline": "Signal you're hiring fast.",
     "features": ["Urgent badge", "Top of category", "30 days live", "Full analytics"]},
    {"id": "premium", "name": "Premium", "price": 129, "tagline": "Maximum reach across NEXORA.",
     "features": ["Homepage placement", "Featured + Urgent badges", "30 days live", "Dedicated support"]},
]

# --- Database-backed data (thin wrappers around job_store) ---
STAGES = ["New", "Shortlisted", "Interview", "Hired"]


def all_jobs():
    import job_store
    return job_store.all_jobs()


def live_jobs():
    import job_store
    return job_store.live_jobs()


def get_job(job_id):
    import job_store
    return job_store.get_job(job_id)


def jobs_for_employer(employer):
    import job_store
    return job_store.jobs_for_employer(employer)


def candidates_for_employer(employer):
    import job_store
    return job_store.candidates_for_employer(employer)


def salary_label(job):
    return f"${job['salary_min']:,} - ${job['salary_max']:,}"
