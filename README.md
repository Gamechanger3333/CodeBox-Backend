# CodeBox Backend — REST API

Node.js/Express backend for the CodeBox online coding platform.

## 🛠️ Tech Stack
- Node.js + Express.js
- PostgreSQL + Prisma (ORM)
- JWT Authentication (httpOnly cookies)
- Groq (GPT-OSS 120B) for AI features
- Resend for transactional email (OTP password reset)
- REST API

## 🎭 Demo Access

Try the app instantly, no signup or OTP verification required:

```
Email: demo@codebox.com
Password: Demo@1234
```
(Note: demo data resets automatically on every demo login — real signup is also available.)

Click **"Try Demo Account"** on the login page to auto-fill and sign in with one click.

### How it works
- The demo account is a normal `User` row — same login/JWT flow as everyone else, no special-cased auth path.
- On every successful demo login, its conversations, snippets, and any uploaded project/interview data are wiped and reseeded with a curated sample set (5 chat conversations, 15 code snippets) — see `utils/demoUser.js`.
- The demo email is reserved: signing up with it is blocked.
- To (re)seed the demo account manually (e.g. first deploy): `npm run seed`.
- Configure the account via `DEMO_USER_EMAIL` / `DEMO_USER_PASSWORD_SEED` in `.env` (see `.env.example`).

## ⚙️ Setup Locally

1. Clone the repo
2. Run `npm install`
3. Copy `.env.example` to `.env` and fill in real values:
   - `DATABASE_URL` — PostgreSQL connection string
   - `JWT_SECRET` — long random string
   - `GROQ_API_KEY` — from console.groq.com
   - `RESEND_API_KEY` — from resend.com
   - `EMAIL_FROM` — a verified sender address (required in production; falls back to the Resend sandbox address in development)
4. Run database migrations: `npx prisma migrate deploy` (or `npx prisma migrate dev` locally)
5. Generate the Prisma client: `npx prisma generate`
6. Seed the demo account: `npm run seed`
7. Run `npm run dev` (development, with auto-reload) or `npm start` (production)

## 📋 Notes

- If `GROQ_API_KEY` or `RESEND_API_KEY` is missing, the server still boots normally — only the specific AI / email features that depend on that key will return a `503` until the key is configured. Other features (auth, snippets, conversations) are unaffected.
- Health check: `GET /health`
- Run `npm test` for the test suite (currently a placeholder — contributions welcome).
