"""
Job Matching Engine.

Scores every live job against a seeker's profile + resume + skills + preferences and returns a
0-99 match percentage. Pure functions (no Flask / database) so the rules are easy to read and test.

    skills match ......... 60  job skill tags found in the seeker's skills/interests (full credit)
                               or mentioned in their resume summary / experience (60% credit)
    role/title fit ....... 25  overlap between the seeker's headline and the job title
    location ............. 7   preferred (or current) location, or a remote role
    work mode ............ 4   on-site / hybrid / remote preference
    job type ............. 4   full-time / part-time / ...

Unset preferences earn half credit so new users aren't punished for leaving them blank.
Free plan shows the top FREE_PLAN_LIMIT matches; Premium shows every match above MATCH_THRESHOLD.
"""
import re

FREE_PLAN_LIMIT = 3
MATCH_THRESHOLD = 40

W_SKILLS, W_TITLE, W_LOCATION, W_MODE, W_TYPE = 60, 25, 7, 4, 4

_STOP = {"senior", "junior", "lead", "principal", "head", "the", "and", "of", "for", "a", "an", "in", "at",
         "to", "mid", "level", "associate", "specialist", "manager"}
_SYNONYMS = {"developer": "engineer", "programmer": "engineer", "engineering": "engineer",
             "coder": "engineer", "dev": "engineer", "analytics": "analyst"}


def _key(text):
    """'Node.js' / 'node js' / 'NodeJS' -> 'nodejs'"""
    return re.sub(r"[^a-z0-9+#]", "", (text or "").lower())


def _title_tokens(text):
    words = re.findall(r"[a-z0-9+#]+", (text or "").lower())
    return {_SYNONYMS.get(w, w) for w in words if len(w) > 1 and w not in _STOP}


def _place_tokens(text):
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 1}


def _blob(profile, resume):
    parts = [resume["summary"] if resume else "", profile.get("headline", "")]
    for e in profile.get("experience", []):
        parts += [e.get("title", ""), e.get("description", "")]
    for e in profile.get("education", []):
        parts.append(e.get("qualification", ""))
    return " ".join(parts).lower()


def score_job(job, profile, resume=None):
    """Return (score, matched_skills) for one job."""
    declared = {_key(s) for s in profile.get("skills", []) + profile.get("interests", [])}
    blob = re.sub(r"[^a-z0-9+# ]", "", _blob(profile, resume))
    blob_nospace = blob.replace(" ", "")

    credit, matched = 0.0, []
    for tag in job["tags"]:
        k = _key(tag)
        if k and k in declared:
            credit += 1.0
            matched.append(tag)
        elif k and k in blob_nospace:
            credit += 0.6
            matched.append(tag)
    skills_pts = W_SKILLS * (credit / len(job["tags"])) if job["tags"] else 0

    want, have = _title_tokens(profile.get("headline", "")), _title_tokens(job["title"])
    title_pts = W_TITLE * (len(want & have) / len(have)) if want and have else 0

    pref_loc = profile.get("pref_location") or profile.get("location")
    if job["mode"] == "Remote":
        loc_pts = W_LOCATION
    elif pref_loc:
        loc_pts = W_LOCATION if _place_tokens(pref_loc) & _place_tokens(job["location"]) else 0
    else:
        loc_pts = W_LOCATION / 2

    def pref(value, actual, weight):
        return weight / 2 if not value else (weight if value == actual else 0)

    mode_pts = pref(profile.get("pref_work_mode"), job["mode"], W_MODE)
    type_pts = pref(profile.get("pref_job_type"), job["type"], W_TYPE)

    score = round(skills_pts + title_pts + loc_pts + mode_pts + type_pts)
    return max(0, min(99, score)), matched


def rank_jobs(jobs, profile, resume=None, exclude_ids=()):
    """All live jobs at or above MATCH_THRESHOLD, best first."""
    ranked = []
    for job in jobs:
        if job["status"] != "Approved" or job["id"] in exclude_ids:
            continue
        score, matched = score_job(job, profile, resume)
        if score >= MATCH_THRESHOLD:
            ranked.append({"job": job, "score": score, "matched": matched})
    ranked.sort(key=lambda m: (-m["score"], m["job"]["posted_days_ago"], m["job"]["id"]))
    return ranked


def split_by_plan(ranked, is_premium):
    """(visible, locked_count). Free users see FREE_PLAN_LIMIT matches; the rest are locked."""
    if is_premium:
        return ranked, 0
    return ranked[:FREE_PLAN_LIMIT], max(0, len(ranked) - FREE_PLAN_LIMIT)
