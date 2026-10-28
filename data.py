"""
NEXORA demo data layer.
In-memory mock data only — no database. State resets on server restart.
This is intentionally simple so it can be swapped for a real DB/API later.
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
]

FIRST_NAMES = ["Ava", "Liam", "Chloe", "Noah", "Mia", "Ethan", "Isla", "Jack",
               "Zoe", "Lucas", "Ruby", "Oliver", "Grace", "Henry", "Amelia", "Leo"]
LAST_NAMES = ["Nguyen", "Smith", "Patel", "Kelly", "Chen", "Walker", "Ahmed",
              "Wilson", "Brown", "Singh", "Taylor", "Robinson", "Lee", "Clarke"]


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


JOBS = _build_jobs()

# --- Applicant pipeline (employer-side, per job) -----------------------
STAGES = ["New", "Shortlisted", "Interview", "Hired"]


def _build_candidates():
    candidates = []
    pool_jobs = [j for j in JOBS if j["company"] == "Northlane Digital"] or JOBS[:4]
    stage_cycle = itertools.cycle(STAGES)
    for i in range(14):
        job = pool_jobs[i % len(pool_jobs)]
        name = f"{FIRST_NAMES[i % len(FIRST_NAMES)]} {LAST_NAMES[i % len(LAST_NAMES)]}"
        candidates.append({
            "id": next_id(),
            "job_id": job["id"],
            "job_title": job["title"],
            "name": name,
            "title": f"{job['experience']} {job['title']}",
            "experience": job["experience"],
            "skills": job["tags"],
            "applied_date": (date.today() - timedelta(days=(i * 2) % 18)).isoformat(),
            "stage": next(stage_cycle) if i % 3 != 0 else "New",
            "avatar_initials": "".join([p[0] for p in name.split()[:2]]),
        })
    return candidates


CANDIDATES = _build_candidates()

# --- Job seeker mock profile & state ------------------------------------
SEEKER = {
    "name": "Jordan Reyes",
    "title": "Frontend Developer",
    "location": "Melbourne, VIC",
    "profile_completion": 85,
    "resume_filename": "Jordan_Reyes_Resume.pdf",
    "skills": ["JavaScript", "React", "CSS", "Figma"],
}

SEEKER_SAVED_JOB_IDS = set([JOBS[2]["id"], JOBS[7]["id"], JOBS[13]["id"]])

SEEKER_APPLICATIONS = [
    {"job_id": JOBS[2]["id"], "stage": "Reviewing", "applied_date": (date.today() - timedelta(days=6)).isoformat()},
    {"job_id": JOBS[15]["id"], "stage": "Interview", "applied_date": (date.today() - timedelta(days=11)).isoformat()},
    {"job_id": JOBS[7]["id"], "stage": "Applied", "applied_date": (date.today() - timedelta(days=2)).isoformat()},
]

APPLICATION_STAGES = ["Applied", "Reviewing", "Interview", "Offer"]

# --- Employer mock account ------------------------------------------------
EMPLOYER = {
    "company": "Northlane Digital",
    "initials": "ND",
    "color": "#5D4FE0",
    "jobs_posted_ids": [j["id"] for j in JOBS if j["company"] == "Northlane Digital"],
}

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

# --- Draft job used by the Post a Job wizard (single demo draft) --------
DRAFT_JOB = {}

# --- Admin mock platform data ---------------------------------------------
PLATFORM_STATS = {
    "total_users": 8420,
    "employers": 612,
    "revenue_month": 18420,
}

ADMIN_REPORTS = [
    {"id": next_id(), "type": "Job listing", "reason": "Misleading salary range",
     "target": "Retail Supervisor — Bright Retail Co.", "status": "Open"},
    {"id": next_id(), "type": "Employer", "reason": "Duplicate company profile",
     "target": "Southwind Logistics", "status": "Open"},
    {"id": next_id(), "type": "Job listing", "reason": "Suspicious contact request",
     "target": "Data Analyst — Ridgeline Analytics", "status": "Resolved"},
]

# Set a few jobs to Pending for the moderation demo
for idx in (1, 9, 17):
    JOBS[idx]["status"] = "Pending"


def get_job(job_id):
    for j in JOBS:
        if j["id"] == job_id:
            return j
    return None


def salary_label(job):
    return f"${job['salary_min']:,} - ${job['salary_max']:,}"
