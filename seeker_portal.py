"""
Job-seeker portal: dashboard data, My Profile, My Applications, Resume Builder,
Job Matches, Upgrade Plan, and the JSON APIs behind Save / Apply.
"""
import os
from datetime import date
from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import data
import matching
import seeker_store as store
import validators as v
from seeker_auth import bp, current_seeker, seeker_required

api_bp = Blueprint("seeker_api", __name__)

WORK_RIGHTS = ["Australian citizen", "Permanent resident", "Work visa (full work rights)",
               "Work visa (limited work rights)", "Student visa", "Other"]
SECTION_KEYS = [s["key"] for s in store.PROFILE_SECTIONS]
MAX_EDU, MAX_EXP = 5, 5


# --------------------------------------------------------------- shared --
def _live_jobs():
    return [j for j in data.JOBS if j["status"] == "Approved"]


def portal_context():
    """Everything the dashboard and sibling pages need about the signed-in seeker."""
    row = current_seeker()
    profile = store.get_profile(row["id"])
    resume = store.get_resume(row["id"])
    percent, sections = store.profile_completion(row, profile)
    applied = store.applied_job_ids(row["id"])
    ranked = matching.rank_jobs(data.JOBS, profile, resume, applied)
    visible, locked = matching.split_by_plan(ranked, row["plan"] == "premium")
    return {
        "row": row, "profile": profile, "resume": resume,
        "percent": percent, "sections": sections,
        "resume_status": store.resume_status(row, profile, resume),
        "matches": visible, "locked_count": locked, "total_matches": len(ranked),
        "is_premium": row["plan"] == "premium",
    }


def _applications_view(seeker_id):
    out = []
    for a in store.get_applications(seeker_id):
        job = data.get_job(a["job_id"])
        if job:
            out.append({**a, "job": job, "applied_label": store.format_date(a["applied_at"])})
    return out


def _csv_list(raw, max_items, max_len=40):
    seen, items = set(), []
    for part in (raw or "").replace("\n", ",").split(","):
        item = v.clean_text(part, max_len)
        if item and item.lower() not in seen:
            seen.add(item.lower())
            items.append(item)
    return items[:max_items]


def _pad(rows, minimum, maximum, blank):
    rows = list(rows)[:maximum]
    target = min(maximum, max(minimum, len(rows) + 1))
    return rows + [dict(blank) for _ in range(target - len(rows))]


def _valid_url(value):
    if not value:
        return True
    u = urlparse(value)
    return u.scheme in ("http", "https") and bool(u.netloc) and len(value) <= 200


# --------------------------------------------------------- My Profile --
EDU_BLANK = {"qualification": "", "institution": "", "year": ""}
EXP_BLANK = {"title": "", "company": "", "start": "", "end": "", "description": ""}


def _profile_values(row, profile):
    return {
        "full_name": row["full_name"], "headline": profile["headline"], "phone": profile["phone"],
        "location": profile["location"],
        "education": profile["education"], "experience": profile["experience"],
        "no_experience": profile["no_experience"],
        "skills": ", ".join(profile["skills"]), "interests": ", ".join(profile["interests"]),
        "pref_job_type": profile["pref_job_type"], "pref_work_mode": profile["pref_work_mode"],
        "pref_location": profile["pref_location"], "work_rights": profile["work_rights"],
        "linkedin": profile["linkedin"], "portfolio": profile["portfolio"],
    }


def _render_profile(values=None, errors=None, open_section=None):
    ctx = portal_context()
    vals = values or _profile_values(ctx["row"], ctx["profile"])
    missing = [s for s in ctx["sections"] if not s["done"]]
    if open_section is None and request.args.get("edit") in SECTION_KEYS:
        open_section = request.args["edit"]
    if open_section is None and missing:
        open_section = missing[0]["key"]
    return render_template(
        "seeker/profile.html", **ctx, values=vals, errors=errors or {}, open_section=open_section,
        edu_rows=_pad(vals["education"], 2, MAX_EDU, EDU_BLANK),
        exp_rows=_pad(vals["experience"], 2, MAX_EXP, EXP_BLANK),
        job_types=data.JOB_TYPES, work_modes=data.WORK_MODES, locations=data.LOCATIONS,
        work_rights_options=WORK_RIGHTS)


@bp.get("/profile")
@seeker_required
def profile():
    return _render_profile()


@bp.post("/profile/<section>")
@seeker_required
def profile_save(section):
    if section not in SECTION_KEYS:
        return redirect(url_for("seeker.profile"))
    row = current_seeker()
    f = request.form
    ctx_profile = store.get_profile(row["id"])
    values = _profile_values(row, ctx_profile)
    errors, fields = {}, {}

    if section == "basic":
        values.update(full_name=v.clean_text(f.get("full_name"), 80), headline=v.clean_text(f.get("headline"), 80),
                      phone=v.clean_text(f.get("phone"), 20), location=v.clean_text(f.get("location"), 80))
        if len(values["full_name"]) < 2:
            errors["full_name"] = "Enter your full name."
        if not values["headline"]:
            errors["headline"] = "Add a headline, like “Software Developer”."
        digits = v.digits_only(values["phone"])
        if not 8 <= len(digits) <= 15:
            errors["phone"] = "Enter a valid phone number."
        if not values["location"]:
            errors["location"] = "Tell us where you're based."
        fields = {k: values[k] for k in ("headline", "phone", "location")}

    elif section == "education":
        rows = []
        for q, i, y in zip(f.getlist("edu_qualification"), f.getlist("edu_institution"), f.getlist("edu_year")):
            q, i, y = v.clean_text(q, 100), v.clean_text(i, 100), v.clean_text(y, 4)
            if not (q or i or y):
                continue
            rows.append({"qualification": q, "institution": i, "year": y})
        rows = rows[:MAX_EDU]
        values["education"] = rows
        for n, r in enumerate(rows):
            if not r["qualification"] or not r["institution"]:
                errors["education"] = "Each entry needs a qualification and an institution."
            elif r["year"] and not (r["year"].isdigit() and 1950 <= int(r["year"]) <= date.today().year + 6):
                errors["education"] = "Use a 4-digit year, like 2024."
        fields = {"education": rows}

    elif section == "skills":
        skills, interests = _csv_list(f.get("skills"), 30), _csv_list(f.get("interests"), 15)
        values.update(skills=", ".join(skills), interests=", ".join(interests))
        if len(skills) < 3:
            errors["skills"] = "Add at least 3 skills, separated by commas."
        fields = {"skills": skills, "interests": interests}

    elif section == "experience":
        rows = []
        for t, c, s_, e, d in zip(f.getlist("exp_title"), f.getlist("exp_company"), f.getlist("exp_start"),
                                  f.getlist("exp_end"), f.getlist("exp_description")):
            t, c = v.clean_text(t, 100), v.clean_text(c, 100)
            s_, e, d = v.clean_text(s_, 20), v.clean_text(e, 20), (d or "").strip()[:500]
            if not (t or c or s_ or e or d):
                continue
            rows.append({"title": t, "company": c, "start": s_, "end": e, "description": d})
        rows = rows[:MAX_EXP]
        no_exp = f.get("no_experience") == "1"
        values.update(experience=rows, no_experience=no_exp)
        if any(not r["title"] or not r["company"] for r in rows):
            errors["experience"] = "Each role needs a job title and a company."
        elif not rows and not no_exp:
            errors["experience"] = "Add a role, or tick “I don't have work experience yet”."
        fields = {"experience": rows, "no_experience": no_exp and not rows}

    elif section == "additional":
        jt, wm = f.get("pref_job_type", ""), f.get("pref_work_mode", "")
        wr = f.get("work_rights", "")
        values.update(pref_job_type=jt if jt in data.JOB_TYPES else "",
                      pref_work_mode=wm if wm in data.WORK_MODES else "",
                      pref_location=v.clean_text(f.get("pref_location"), 60),
                      work_rights=wr if wr in WORK_RIGHTS else "",
                      linkedin=v.clean_text(f.get("linkedin"), 200), portfolio=v.clean_text(f.get("portfolio"), 200))
        if not values["work_rights"]:
            errors["additional"] = "Choose your work rights."
        elif not (values["pref_job_type"] or values["pref_work_mode"] or values["pref_location"]):
            errors["additional"] = "Add at least one job preference so we can match you better."
        for key in ("linkedin", "portfolio"):
            if not _valid_url(values[key]):
                errors["additional"] = "Links must start with https://"
        fields = {k: values[k] for k in ("pref_job_type", "pref_work_mode", "pref_location", "work_rights",
                                         "linkedin", "portfolio")}

    if errors:
        return _render_profile(values=values, errors=errors, open_section=section), 422
    if section == "basic":
        store.update_seeker(row["id"], full_name=values["full_name"])
    store.save_profile_fields(row["id"], **fields)
    flash(f"{next(s['label'] for s in store.PROFILE_SECTIONS if s['key'] == section)} saved.", "success")
    return redirect(url_for("seeker.profile"))


# ---------------------------------------------------- My Applications --
@bp.get("/applications")
@seeker_required
def applications():
    row = current_seeker()
    apps = _applications_view(row["id"])
    counts = {s: sum(1 for a in apps if a["status"] == s) for s in store.APPLICATION_STATUSES}
    active = request.args.get("status")
    shown = [a for a in apps if a["status"] == active] if active in store.APPLICATION_STATUSES else apps
    return render_template("seeker/applications.html", apps=shown, total=len(apps), counts=counts,
                           active=active if active in store.APPLICATION_STATUSES else None,
                           statuses=store.APPLICATION_STATUSES)


# ------------------------------------------------------ Resume Builder --
@bp.route("/resume", methods=["GET", "POST"])
@seeker_required
def resume():
    row = current_seeker()
    profile = store.get_profile(row["id"])
    existing = store.get_resume(row["id"])
    if request.method == "POST":
        template = request.form.get("template", "modern")
        if template not in {t["id"] for t in store.RESUME_TEMPLATES}:
            template = "modern"
        summary = v.clean_text(request.form.get("summary"), 600)
        store.save_resume(row["id"], template, summary)
        saved = store.get_resume(row["id"])
        status = store.resume_status(row, profile, saved)
        flash("Resume saved. It's now used for job matching." if status == "Completed"
              else "Resume saved. Complete the checklist to finish it.", "success")
        return redirect(url_for("seeker.resume"))
    current = existing or {"template": "modern", "summary": "", "updated_at": ""}
    return render_template(
        "seeker/resume.html", row=row, profile=profile, resume=existing, current=current,
        templates=store.RESUME_TEMPLATES, status=store.resume_status(row, profile, existing),
        requirements=store.resume_requirements(row, profile, existing),
        updated_label=store.format_date(existing["updated_at"]) if existing else "")


# --------------------------------------------------------- Job matches --
@bp.get("/matches")
@seeker_required
def matches():
    return render_template("seeker/matches.html", **portal_context(), free_limit=matching.FREE_PLAN_LIMIT)


# -------------------------------------------------------- Upgrade Plan --
def _demo_upgrades_enabled():
    return os.environ.get("NEXORA_DEMO_UPGRADE", "1") != "0"


@bp.get("/upgrade")
@seeker_required
def upgrade():
    ctx = portal_context()
    return render_template("seeker/upgrade.html", **ctx, demo_enabled=_demo_upgrades_enabled(),
                           free_limit=matching.FREE_PLAN_LIMIT)


@bp.post("/upgrade")
@seeker_required
def upgrade_post():
    row = current_seeker()
    plan = request.form.get("plan")
    if plan not in store.PLANS:
        return redirect(url_for("seeker.upgrade"))
    if not _demo_upgrades_enabled():
        flash("Online payments are coming soon.", "info")
        return redirect(url_for("seeker.upgrade"))
    store.update_seeker(row["id"], plan=plan)
    flash("You're on Premium. All your matching jobs are unlocked." if plan == "premium"
          else "You're back on the Free plan.", "success")
    return redirect(url_for("seeker.matches" if plan == "premium" else "seeker.upgrade"))


# ------------------------------------------------------------ JSON APIs --
@api_bp.post("/api/jobs/<int:job_id>/save")
@seeker_required
def api_toggle_save(job_id):
    if not data.get_job(job_id):
        return jsonify({"ok": False, "error": "Job not found."}), 404
    row = current_seeker()
    saved = store.toggle_saved(row["id"], job_id)
    return jsonify({"ok": True, "saved": saved, "saved_count": len(store.saved_job_ids(row["id"]))})


@api_bp.post("/api/jobs/<int:job_id>/apply")
@seeker_required
def api_apply(job_id):
    job = data.get_job(job_id)
    if not job or job["status"] != "Approved":
        return jsonify({"ok": False, "error": "This job is no longer open."}), 404
    row = current_seeker()
    note = ((request.get_json(silent=True) or {}).get("cover_note") or "").strip()[:1000]
    created = store.add_application(row["id"], job_id, note)
    if created:
        job["applications_count"] += 1
        app_row = next(a for a in store.get_applications(row["id"]) if a["job_id"] == job_id)
        profile = store.get_profile(row["id"])
        data.add_applicant(row["id"], app_row["id"], row["full_name"] or row["email"], profile["headline"],
                           profile["skills"], job)
    return jsonify({"ok": True, "already_applied": not created})


@api_bp.post("/api/seeker/applications/<int:application_id>/status")
@seeker_required
def api_application_status(application_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in store.APPLICATION_STATUSES:
        return jsonify({"ok": False, "error": "Unknown status."}), 400
    if not store.set_application_status(current_seeker()["id"], application_id, status):
        return jsonify({"ok": False, "error": "Application not found."}), 404
    return jsonify({"ok": True, "status": status})


@api_bp.post("/api/seeker/applications/<int:application_id>/remove")
@seeker_required
def api_application_remove(application_id):
    row = current_seeker()
    app_row = store.get_application(row["id"], application_id)
    if not app_row or not store.remove_application(row["id"], application_id):
        return jsonify({"ok": False, "error": "Application not found."}), 404
    job = data.get_job(app_row["job_id"])
    if job and job["applications_count"] > 0:
        job["applications_count"] -= 1
    data.remove_applicant(row["id"], application_id)
    return jsonify({"ok": True})
