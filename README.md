# Rate BIPH

Anonymous teacher reviews for Beijing International Private High (BIPH). Live at **[ratebiph.com](https://ratebiph.com)**.

Replaces the slow base44 no-code site (biphratemyteacher.base44.app) with real infrastructure we control.

## What's here

- **4-metric reviews** — Teaching quality, Test difficulty, Homework load, Easygoingness (each 1–5)
- **Anonymous** — no login, IP is salted-hashed for rate limiting only
- **Spam guards** — Cloudflare Turnstile, 5 reviews/day/IP, 1 review/teacher/IP/7 days, duplicate-comment block
- **Admin** — token-gated page to approve teacher submissions and hide abusive reviews
- **Seeded** — 63 teachers + 962+ reviews imported from the base44 site on first deploy

## Stack

| Layer | What |
|---|---|
| Backend | FastAPI (Python 3.9+), serves both `/api/*` and the static frontend |
| DB | SQLite on a Railway persistent volume |
| Frontend | Vanilla HTML/CSS/JS — no build step |
| Spam | Cloudflare Turnstile |
| Hosting | Railway (one service, one domain) |

Single-origin hosting means no CORS headaches and one bill.

## Layout

```
biph-ratings/
├── backend/
│   ├── main.py              FastAPI routes + static mount
│   ├── db.py                SQLite connection helper
│   ├── schema.sql           Tables + indexes
│   ├── spam.py              Turnstile + rate limits
│   ├── seed.py              One-time base44 import (idempotent)
│   └── requirements.txt
├── frontend/
│   ├── index.html           Search + roster
│   ├── teacher.html         Profile + review form
│   ├── submit.html          Propose a new teacher
│   ├── admin.html           Approve submissions, hide reviews
│   ├── styles.css
│   ├── app.js               Stars, avatars, Turnstile, fetch helpers
│   └── config.js            API_BASE + TURNSTILE_SITEKEY (edit for prod)
├── railway.json
├── .gitignore
└── README.md
```

## Run locally

```bash
cd biph-ratings
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# One-time: import teachers + reviews from base44
python -m backend.seed

# Start the server (serves frontend + API on one port)
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 — the roster loads.
Admin: http://127.0.0.1:8000/admin.html — token `dev-admin-token`.

> **macOS gotcha:** if uvicorn fails with `PermissionError` on Desktop, run from a non-sandboxed path (e.g. `~/.biph-ratings/`). macOS TCC blocks some child processes from reading Desktop.

## Deploy to ratebiph.com

### 1. Register a Cloudflare Turnstile site

1. Go to https://dash.cloudflare.com/?to=/:account/turnstile and **Add site**.
2. Domain: `ratebiph.com` (add `localhost` too if you want local Turnstile in dev).
3. Widget mode: **Managed**.
4. Copy the **Site Key** and **Secret Key**.

### 2. Push to GitHub

```bash
cd /Users/mingkai/Desktop/biph-ratings
git init
git add .
git commit -m "Initial commit: Rate BIPH"
gh repo create Mingkai1207/biph-ratings --public --source=. --push
```

### 3. Deploy on Railway

1. https://railway.com → **New Project → Deploy from GitHub** → pick `biph-ratings`.
2. Railway auto-detects Python via `railway.json`.
3. Once built, open the service → **Settings → Variables** and add:

   | Key | Value |
   |---|---|
   | `TURNSTILE_SITEKEY` | (from step 1) |
   | `TURNSTILE_SECRET` | (from step 1) |
   | `TURNSTILE_ENABLED` | `1` |
   | `ADMIN_TOKEN` | a long random string — `openssl rand -hex 32` |
   | `IP_HASH_SALT` | another long random string |
   | `ALLOWED_ORIGIN` | `https://ratebiph.com` |
   | `BIPH_DB_PATH` | `/data/biph.db` |

4. **Settings → Volumes → New Volume** → mount path `/data`, size `1 GB`. This keeps the SQLite DB across deploys.

5. Edit `frontend/config.js` and push — set `TURNSTILE_SITEKEY` to the real site key. `API_BASE` stays empty (same-origin).

6. **Settings → Networking → Generate Domain** (get the `*.up.railway.app` URL to confirm it's live) and then **Add Custom Domain → `ratebiph.com`** (and `www.ratebiph.com`). Railway shows a CNAME target.

### 4. Point ratebiph.com at Railway

Wherever you bought the domain (Namecheap, Porkbun, Cloudflare, etc.):

| Type | Name | Value |
|---|---|---|
| CNAME | `@` (or `apex` / ALIAS) | the Railway-provided target |
| CNAME | `www` | the Railway-provided target |

If your registrar doesn't support CNAME-on-apex, either use their ALIAS/ANAME record, or put the domain behind Cloudflare (free tier) which flattens CNAMEs at the apex.

DNS propagates in 5–60 min. Railway issues the TLS cert automatically once it verifies.

### 5. Seed production data

One-time, from your laptop against production:

```bash
# Option A — exec into the Railway container
railway run python -m backend.seed

# Option B — point a local seed run at the volume via temporary SSH/shell
```

Or just commit a pre-seeded `biph.db` to the volume: copy your local `backend/biph.db` via `railway volume` tools.

### 6. Verify

- `https://ratebiph.com/api/health` → `{"ok": true}`
- `https://ratebiph.com/` → roster loads with 63 teachers
- Submit a test review → appears on the teacher's profile
- Turnstile widget is visible (not the test-mode "always passes" one)

## Admin

- Go to `https://ratebiph.com/admin.html`
- Paste `ADMIN_TOKEN`
- Approve / reject pending teacher submissions
- Hide abusive reviews by pasting the review UUID (find it in the DB or via the API)

## Spam tuning

All in `backend/spam.py`:

- `TEACHER_COOLDOWN_DAYS = 7`
- `MIN_COMMENT_LEN = 20`, `MAX_COMMENT_LEN = 2000`

Change, redeploy. Rate limits are per salted-IP-hash, so changing `IP_HASH_SALT` in env rotates everyone's limit window.

## Re-seeding

`backend/seed.py` is idempotent — it upserts by base44's `legacy_id`. Safe to re-run anytime. It won't touch reviews posted on ratebiph.com (those have no `legacy_id`).

## Costs

- Railway Hobby: **$5/mo** (includes the volume for SQLite)
- Cloudflare Turnstile: **free**
- Domain: ~$10/yr

If SQLite ever gets cramped (unlikely before thousands of monthly reviews), swap `db.py` to `asyncpg` against Railway Postgres. Schema ports cleanly — the only change is `gen_random_uuid()` in defaults.

## License

Private project for BIPH students.
