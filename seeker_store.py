"""Supabase-backed seeker accounts, profiles, resumes, applications and saved jobs."""
import json
from datetime import datetime, timezone
from db import get_db

APPLICATION_STATUSES = ["Applied", "Shortlisted", "Interview", "Rejected"]
RESUME_TEMPLATES = [
 {"id":"modern","name":"Modern","blurb":"Bold header with an indigo accent."},
 {"id":"classic","name":"Classic","blurb":"Traditional serif layout."},
 {"id":"minimal","name":"Minimal","blurb":"Clean, spacious and simple."},]
PLANS=("free","premium")
PROFILE_SECTIONS=[
 {"key":"basic","label":"Basic Information","weight":25,"icon":"user-round"},
 {"key":"education","label":"Education Details","weight":20,"icon":"graduation-cap"},
 {"key":"skills","label":"Skills & Interests","weight":25,"icon":"sparkles"},
 {"key":"experience","label":"Work Experience","weight":20,"icon":"briefcase"},
 {"key":"additional","label":"Additional Details","weight":10,"icon":"list-plus"}]
_JSON_COLS=("education","experience","skills","interests")
def _one(table, **filters):
 q=get_db().table(table).select("*")
 for k,v in filters.items(): q=q.eq(k,v)
 rows=q.limit(1).execute().data or []
 return rows[0] if rows else None
def _now(): return datetime.now(timezone.utc).isoformat()
def get_seeker(seeker_id): return _one("seekers",id=seeker_id) if seeker_id else None
def get_seeker_by_email(email): return _one("seekers",email=(email or "").lower())
def get_seeker_by_google_sub(sub): return _one("seekers",google_sub=sub)
def create_seeker(email,full_name="",password_hash=None,google_sub=None,is_demo=False):
 row=get_db().table("seekers").insert({"email":email.lower(),"full_name":full_name,"password_hash":password_hash,"google_sub":google_sub,"is_demo":bool(is_demo)}).execute().data[0]
 sid=row["id"]
 get_db().table("seeker_profiles").upsert({"seeker_id":sid},on_conflict="seeker_id").execute()
 return sid
def update_seeker(seeker_id,**fields):
 allowed={"password_hash","google_sub","full_name","plan"}; values={k:v for k,v in fields.items() if k in allowed}
 if values: get_db().table("seekers").update(values).eq("id",seeker_id).execute()
def touch_login(seeker_id): get_db().table("seekers").update({"last_login_at":_now()}).eq("id",seeker_id).execute()
def seeker_display(row):
 name=(row["full_name"] or "").strip() or row["email"].split("@")[0]; parts=[p for p in name.split() if p]
 return {"id":row["id"],"email":row["email"],"full_name":name,"first_name":parts[0] if parts else name,"initials":("".join(p[0] for p in parts[:2]) or name[:1]).upper(),"plan":row["plan"],"is_premium":row["plan"]=="premium"}
def get_profile(seeker_id):
 row=_one("seeker_profiles",seeker_id=seeker_id)
 if row is None:
  get_db().table("seeker_profiles").upsert({"seeker_id":seeker_id},on_conflict="seeker_id").execute(); row=_one("seeker_profiles",seeker_id=seeker_id)
 p=dict(row)
 for col in _JSON_COLS:
  val=p.get(col,[])
  if isinstance(val,str):
   try: val=json.loads(val or "[]")
   except ValueError: val=[]
  p[col]=val or []
 p["no_experience"]=bool(p.get("no_experience")); return p
def save_profile_fields(seeker_id,**fields):
 allowed={"headline","phone","location","education","experience","no_experience","skills","interests","pref_job_type","pref_work_mode","pref_location","work_rights","linkedin","portfolio"}
 values={k:v for k,v in fields.items() if k in allowed}
 for k in _JSON_COLS:
  if k in values and isinstance(values[k],str):
   try: values[k]=json.loads(values[k])
   except ValueError: values[k]=[]
 if "no_experience" in values: values["no_experience"]=bool(values["no_experience"])
 if values: values["updated_at"]=_now(); get_db().table("seeker_profiles").update(values).eq("seeker_id",seeker_id).execute()
def profile_completion(seeker,profile):
 done={"basic":bool((seeker["full_name"] or "").strip() and profile["headline"] and profile["phone"] and profile["location"]),"education":bool(profile["education"]),"skills":len(profile["skills"])>=3,"experience":bool(profile["experience"]) or profile["no_experience"],"additional":bool(profile["work_rights"] and (profile["pref_location"] or profile["pref_job_type"] or profile["pref_work_mode"]))}
 sections=[{**s,"done":done[s["key"]]} for s in PROFILE_SECTIONS]; return sum(s["weight"] for s in sections if s["done"]),sections
def get_resume(seeker_id): return _one("seeker_resumes",seeker_id=seeker_id)
def save_resume(seeker_id,template,summary): get_db().table("seeker_resumes").upsert({"seeker_id":seeker_id,"template":template,"summary":summary,"updated_at":_now()},on_conflict="seeker_id").execute()
def resume_requirements(seeker,profile,resume):
 return [{"label":"Professional summary (40+ characters)","done":bool(resume and len(resume["summary"])>=40),"where":"resume"},{"label":"Headline & contact details","done":bool(profile["headline"] and profile["phone"] and profile["location"]),"where":"basic"},{"label":"Education or work experience","done":bool(profile["education"] or profile["experience"]),"where":"education"},{"label":"At least 3 skills","done":len(profile["skills"])>=3,"where":"skills"}]
def resume_status(seeker,profile,resume):
 if not resume:return "Not started"
 return "Completed" if all(r["done"] for r in resume_requirements(seeker,profile,resume)) else "In progress"
def get_applications(seeker_id): return (get_db().table("applications").select("*").eq("seeker_id",seeker_id).order("applied_at",desc=True).order("id",desc=True).execute().data or [])
def applied_job_ids(seeker_id): return {r["job_id"] for r in (get_db().table("applications").select("job_id").eq("seeker_id",seeker_id).execute().data or [])}
def add_application(seeker_id,job_id,cover_note=""):
 if get_db().table("applications").select("id").eq("seeker_id",seeker_id).eq("job_id",job_id).limit(1).execute().data:return False
 get_db().table("applications").insert({"seeker_id":seeker_id,"job_id":job_id,"cover_note":cover_note}).execute(); return True
def get_application(seeker_id,application_id): return _one("applications",id=application_id,seeker_id=seeker_id)
def set_application_status(seeker_id,application_id,status):
 if not _one("applications",id=application_id,seeker_id=seeker_id):return False
 get_db().table("applications").update({"status":status,"updated_at":_now()}).eq("id",application_id).eq("seeker_id",seeker_id).execute(); return True
def remove_application(seeker_id,application_id):
 if not _one("applications",id=application_id,seeker_id=seeker_id):return False
 get_db().table("applications").delete().eq("id",application_id).eq("seeker_id",seeker_id).execute(); return True
def saved_job_ids(seeker_id): return [r["job_id"] for r in (get_db().table("saved_jobs").select("job_id").eq("seeker_id",seeker_id).order("saved_at",desc=True).execute().data or [])]
def toggle_saved(seeker_id,job_id):
 row=_one("saved_jobs",seeker_id=seeker_id,job_id=job_id)
 if row: get_db().table("saved_jobs").delete().eq("seeker_id",seeker_id).eq("job_id",job_id).execute(); return False
 get_db().table("saved_jobs").insert({"seeker_id":seeker_id,"job_id":job_id}).execute(); return True
def format_date(value):
 try:
  d=datetime.strptime(value[:10],"%Y-%m-%d"); return f"{d.day} {d:%b %Y}"
 except (ValueError,TypeError): return value or ""
