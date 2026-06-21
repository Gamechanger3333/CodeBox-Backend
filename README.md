# CodeBox Backend — REST API

Node.js/Express backend for the CodeBox online coding platform.

## 🛠️ Tech Stack
- Node.js + Express.js
- PostgreSQL + Prisma (ORM)
- JWT Authentication (httpOnly cookies)
- Groq (Llama 3.3 70B) for AI features
- Resend for transactional email (OTP password reset)
- REST API

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
6. Run `npm run dev` (development, with auto-reload) or `npm start` (production)

## 📋 Notes

- If `GROQ_API_KEY` or `RESEND_API_KEY` is missing, the server still boots normally — only the specific AI / email features that depend on that key will return a `503` until the key is configured. Other features (auth, snippets, conversations) are unaffected.
- Health check: `GET /health`
- Run `npm test` for the test suite (currently a placeholder — contributions welcome).
