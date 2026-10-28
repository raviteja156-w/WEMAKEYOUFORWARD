# NEXORA — Client Demo

A high-fidelity, frontend-focused demo of NEXORA, an Australian employment marketplace.
This is **not** a production application — it's an interactive client demonstration built
with Flask, Jinja templates, Tailwind CSS and vanilla JavaScript, using mock data held in
memory (no database).

## Run it

```
pip install flask
python app.py
```

Then open **http://127.0.0.1:5000**.

## Demo mode

Use the "Demo mode" control in the bottom-left corner to switch between **Visitor**,
**Job Seeker**, **Employer** and **Admin** views. This simulates authentication for the
purposes of the demo — there is no real login system.

## Suggested walkthrough

1. **Visitor** — Landing page → Find Jobs → filter/sort → open a Job Details page → Apply Now.
2. **Job Seeker** — Dashboard shows the application pipeline, saved jobs and recommended roles.
3. **Employer** — Dashboard → Post a Job (4-step wizard) → choose a package → simulated
   payment → job goes live → Applicants board to move candidates through the hiring pipeline.
4. **Admin** — Marketplace metrics, job moderation queue (Approve / Reject / Review / Suspend)
   and platform reports.

## Notes for engineering handoff

- All data lives in `data.py` as in-memory Python structures — swap this layer for real
  models/DB calls when moving to production.
- Interactive state changes (save job, apply, post job, checkout, stage moves, moderation)
  go through small JSON API endpoints in `app.py` (`/api/...`) so the same endpoints can be
  re-pointed at real persistence later.
- No authentication, payments, email or AI matching are implemented — all are simulated for
  demo purposes only, as noted inline in the UI (e.g. match percentages, checkout).

## Structure

```
nexora/
├── app.py                  Flask routes + mock-state API endpoints
├── data.py                 Mock data (jobs, candidates, seeker/employer/admin state)
├── templates/               Jinja templates (one per screen) + base.html layout
└── static/
    ├── css/custom.css       NEXORA design tokens & shared component styles
    └── js/                  app.js (shared) + per-screen interaction scripts
```
