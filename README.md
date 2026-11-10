# CodeBox API — FastAPI edition

This repository now contains **only** the FastAPI backend (the old Express/Prisma code was removed; it is
preserved in git under the tag `express-final`). It replaces the Express/Prisma CodeBox backend, rewritten in **Python 3.12 + FastAPI + async SQLAlchemy**.
Same URLs, same JSON, same cookies, **same PostgreSQL database** — the Next.js frontend works unchanged
(point `NEXT_PUBLIC_API_URL` at this server, still ending in `/api`).

| Concern | Express version | This version |
|---|---|---|
| HTTP framework | Express | FastAPI (ASGI, async) |
| Validation | express-validator | Pydantic v2 models (same messages, same "first error only") |
| DB access | Prisma | SQLAlchemy 2 async + asyncpg, mapped onto the **existing** Prisma tables |
| Auth | jsonwebtoken + bcrypt | PyJWT + bcrypt (old hashes and old tokens keep working) |
| Uploads | multer + jszip | `UploadFile` + `zipfile` |
| Background RAG indexing | un-awaited promise | `BackgroundTasks` |
| Rate limit / headers | express-rate-limit / helmet | small in-memory middleware (same limits) |
| LLM | `groq-sdk` | `groq` (AsyncGroq) |
| Tests | – | pytest, 135 tests against a real PostgreSQL |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                       # fill DATABASE_URL, JWT_SECRET (same as before!), GROQ_API_KEY ...
python -m scripts.init_db                                  # creates only MISSING tables (see "Bugs found" #1)
python -m scripts.seed                                     # optional: demo@codebox.com sample account
uvicorn app.main:app --reload --port 5000                  # docs at http://localhost:5000/docs (not in production)
```

Tested on Python 3.12. `numpy` is optional (faster retrieval); if `pip install numpy` fails on your Python version just skip it.

RAG needs an embedding model: `ollama pull nomic-embed-text` (or set `EMBEDDING_PROVIDER=gemini` + `GEMINI_API_KEY`).
Deploy: `Dockerfile` included (Render/Railway). Set `NODE_ENV=production`, `FRONTEND_URL`, `JWT_SECRET`, `DATABASE_URL`.

## Tests

```bash
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/codebox_test pytest -q
```
Tests use a **real PostgreSQL** (tables are TRUNCATEd between tests — never point this at real data). Only the network edges
are faked: Groq, Ollama embeddings and Resend.

* `test_js_parity.py` replays outputs recorded from the **original Node code** (chunker, ranking parser, file filter,
  JSON parsers, ZIP extraction) and asserts the Python port is identical.
* `test_auth.py` includes a bcrypt hash and a JWT created by the old Node app, proving existing users/tokens still work.

## Layout (read in this order)

```
app/main.py            wiring: middleware order, error handlers, routers
app/config.py          settings from env (same variable names as before)
app/database.py        async engine/session (+ Prisma-URL translation)
app/models.py          tables (exact Prisma table/column names)
app/schemas.py         request validation (Pydantic)
app/security.py        JWT, bcrypt, cookies, get_current_user dependency
app/middleware.py      security headers, rate limiter, global error catcher
app/routers/*.py       auth, conversations, snippets, project, interview
app/services/*.py      groq_client, codebox_ai, rag_engine, project_analyzer, interview_analyzer, email, demo_user
app/prompts.py         every prompt (extracted mechanically from the JS source)
scripts/               init_db, seed, eval_retrieval
```

## Bugs found while porting (all fixed here)

1. **`InterviewSession` did not exist.** `schema.prisma` has no such model and the migration history *drops* the table
   (`20260801165955`), yet the interview controller uses `prisma.interviewSession`. With the repo's migrations applied, every
   `/api/interview/*` call would crash. The model is declared in `app/models.py`; `python -m scripts.init_db` creates the table.
2. **Chat context used the OLDEST 30 messages** (`orderBy asc` + `take 30`), so after 30 messages the model stopped seeing recent
   turns. Now the latest 30 are sent.
3. **Stale interview after re-upload.** The project upsert keeps the same `ProjectSession.id`, so the old interview still looked
   current. A new upload now deletes the old interview.
4. User + bot messages and the demo seed could share one timestamp, making chat order ambiguous → distinct, increasing timestamps.
5. The user's name was inserted raw into the OTP e-mail HTML → now HTML-escaped.
6. Model output with objects but no usable `question` produced an interview with 0 questions → falls back to the default question.
7. Wrong file type / file too large returned a generic 500 → now `400 {"error": "Only ZIP files are accepted"}` / `413`.
8. Re-ranker could return the same index twice (wasting slots) → de-duplicated.
9. The `limit` query validator on `/getAllConversationIDs` was never enforced → clamped to 100.

## Deliberate differences

* `GET /docs` (Swagger UI) exists outside production.
* Rate limits are in-memory (per process), like the original. Use Redis if you run several instances.
* ZIP extraction was checked against the original on 4 real project zips (same file tree, stats and file lists);
  file ordering uses an ICU-like comparator instead of JS `localeCompare`.

## Not verified here

Real calls to Groq / Ollama / Gemini / Resend (no internet in the build sandbox — they are mocked in tests) and the browser UI.
Do one manual pass with real keys: sign up, chat, upload a zip, ask a question, run an interview, reset a password.


## Deploy on Render (free tier)

1. Push this repo to GitHub. **Never commit `.env`** (it is in `.gitignore`).
2. Render dashboard -> New -> Web Service -> pick the repo (or New -> Blueprint, it reads `render.yaml`).
3. Runtime **Python 3**, Build: `pip install -r requirements.txt`,
   Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`, Health check path: `/health`.
4. Environment variables: `NODE_ENV=production`, `DATABASE_URL` (Neon pooled URL), `JWT_SECRET` (same as before),
   `FRONTEND_URL` (exact Vercel URL, no trailing slash), `GROQ_API_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`,
   `EMBEDDING_PROVIDER=gemini` + `GEMINI_API_KEY` (Render cannot run Ollama), `PYTHON_VERSION=3.12.8`.
5. After the first deploy, open **Shell** on the service once and run `python -m scripts.init_db`
   (creates only missing tables, e.g. `InterviewSession`).
6. Frontend: set `NEXT_PUBLIC_API_URL=https://<your-service>.onrender.com/api` and redeploy it.
   Cookies are `Secure; SameSite=None` so frontend and API may live on different domains (HTTPS only).

Free tier note: the service sleeps after ~15 min idle and the Neon database sleeps too, so the first request
after a pause can take 30-60 s. The API starts immediately; the database check runs in the background.

Which backend answers on a port? `/docs` exists only on FastAPI (and only when `NODE_ENV` is not `production`);
`/health` is identical on both versions, so it cannot tell them apart.
