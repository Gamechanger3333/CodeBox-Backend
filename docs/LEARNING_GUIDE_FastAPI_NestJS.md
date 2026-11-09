# FastAPI + NestJS — Seekhne aur Interview ki taiyari ka guide

Ye guide dono rewritten projects par based hai:
**CodeBox → FastAPI** (`codebox-fastapi/`) aur **Nexus Inventory → NestJS** (`nexus-nestjs/`).
Har concept ke saath bataya gaya hai ke wo **kis file mein** hai, taake aap code khol kar saath saath parh sakein.
Technical words English mein hain (interview mein wahi bolne hain).

---

## 0. Kaise parhein (7 din ka plan)

| Din | Kya karna hai |
|---|---|
| 1 | Dono README parho. Dono projects chalao (`/docs` FastAPI mein, `/api/healthz` Nest mein). Frontend se ek login karo. |
| 2 | FastAPI: `main.py` → `security.py` → `routers/auth.py` → `schemas.py`. Har request ka raasta pencil se likho. |
| 3 | FastAPI: `models.py`, `database.py`, `routers/conversations.py`, phir `tests/conftest.py` aur `test_auth.py`. |
| 4 | FastAPI RAG: `services/rag_engine.py` + `routers/project.py` + `tests/test_project_rag.py`. |
| 5 | NestJS: `main.ts` → `app.module.ts` → `common/guards.ts` → `auth/*`. Lifecycle diagram yaad karo (sec. 3.2). |
| 6 | NestJS: `inventory.service.ts`, `sales.service.ts` (transactions), `realtime.gateway.ts`, `test/domain.spec.ts`. |
| 7 | Sec. 6 ke sawalon ke jawab **zubani** do (record kar ke suno). Sec. 8 ki exercises mein se 2 karo. |

Tip: sirf code parhne se interview nahi nikalta. Har file ke baad band kar ke khud se poochho: "ye kyun hai? iske bina kya toot'ta?"

---

## 1. Bird's-eye view

Dono projects **purane Express backends ke drop-in replacement** hain: same URLs, same JSON, same cookies, **same database**.
Is liye frontend change nahi hua. Ye khud ek achhi interview story hai: *"I rewrote a production backend without changing its API contract, and proved it with parity tests."*

| | CodeBox (FastAPI) | Nexus (NestJS) |
|---|---|---|
| Language | Python 3.12 | TypeScript |
| DB layer | SQLAlchemy 2 async (existing Prisma tables par mapped) | Prisma 6 (same schema) |
| Style | Functions + `Depends()` | Classes + decorators + modules |
| Auth | JWT cookie `token` + Bearer | JWT httpOnly cookie + CSRF double-submit |
| Special | RAG, background indexing, AI interview | Multi-tenancy, RBAC, stock transactions, websockets |
| Tests | 135 (pytest, real Postgres) | 54 (Jest e2e, real Postgres) |

---

## 2. FastAPI — concepts jo aap ko aani chahiye

### 2.1 ASGI, async, event loop  (`app/main.py`, `app/security.py`)
* FastAPI **ASGI** par chalta hai (uvicorn server). `async def` endpoint event loop par chalta hai; ek loop hazaron connections sambhalta hai **agar** aap loop ko block na karein.
* Blocking kaam (bcrypt ~250 ms, ZIP extract) seedha `async def` mein karenge to poora server ruk jata hai. Is liye
  `await asyncio.to_thread(...)` — dekho `hash_password()` aur `extract_project_files` ka call (`routers/project.py`).
* Rule: **I/O = await, CPU-heavy = thread/process.**

### 2.2 Pydantic v2 — validation  (`app/schemas.py`)
* Request body ek class hota hai: type hints = validation. FastAPI khud 422 deta hai; hum ne handler (`main.py`) se **pehli galti** wale old shape mein convert kiya (`{"error": msg}` ya `{"status":"error","message":msg}`).
* `validate_default=True` (class `Body`): warna *missing* field par validator chalta hi nahi (ek asli bug jo test ne pakda).
* `BeforeValidator` = pehle trim/coerce, phir rules. `field_validator` = rule.

### 2.3 Dependency Injection — `Depends`  (`security.get_current_user`, `database.get_session`)
* Endpoint ka argument `user: dict = Depends(get_current_user)` — FastAPI pehle dependency chalata hai, phir endpoint.
* **Order matter karta hai**: `conversations.py` mein `user` pehle, `conversation_id_param` baad mein → auth error validation error se pehle aata hai (jaise Express mein tha).
* Testing mein dependencies override ho sakti hain; hum ne seedha service function monkeypatch kiya (`fake_groq`).
* `get_session` ek **generator dependency** hai: `yield` se pehle open, baad mein khud close (har request = ek session).

### 2.4 SQLAlchemy 2 async  (`models.py`, `database.py`)
* `Mapped[...]` + `mapped_column(...)` = typed models. Hum ne **existing Prisma tables** map kiye: table name `"User"`, column `"createdAt"` (camelCase). Python attribute `created_at`, DB column alag naam — `mapped_column("createdAt", ...)`.
* Session = unit of work: `db.add()`, `await db.commit()`. `expire_on_commit=False` taake commit ke baad object ki fields abhi parhi ja sakein.
* **Upsert**: `pg_insert(...).on_conflict_do_update(index_elements=[...], set_={...})` (`routers/project.py`). Ek real bug: `set_` mein *column ka asli naam* chahiye, attribute naam nahi — real Postgres test ne pakda.
* Pooled URL (PgBouncer/Neon): `statement_cache_size=0` (`database.py`).

### 2.5 BackgroundTasks  (`routers/project.py: index_project_in_background`)
* Response bhej dene ke **baad** chalta hai. Naya DB session khud kholte hain (request wala session band ho chuka hota hai).
* Limit: same process mein chalta hai; server restart = kaam gum. Production mein queue (Celery/RQ/ARQ) lagti hai. **Interview mein ye limitation zaroor bolo** — maturity dikhti hai.

### 2.6 Middleware ka order aur CORS gotcha  (`main.py`, `middleware.py`)
* `add_middleware` mein **aakhri add kiya hua sab se bahar** hota hai. Hum chahte hain: CORS → headers → rate limit → error catcher → route.
* Gotcha: `add_exception_handler(Exception, ...)` Starlette ke `ServerErrorMiddleware` mein chalta hai jo CORS **se bahar** hai → 500 response par CORS headers nahi → browser asal error chhupa deta hai ("CORS error"). Isi liye error-catching **middleware** bana (`error_catcher_middleware`). Test: `test_unhandled_errors_are_json_with_cors...`.

### 2.7 Security checklist (code se)
bcrypt (rounds 12, thread mein) • OTP sirf **hash** ho kar store • 5 galat OTP = OTP burn • forgot-password hamesha same jawab (user enumeration nahi) • `algorithms=["HS256"]` pin (alg:none attack) • reset-token se login nahi ho sakta (`purpose` claim) • cookie `httponly; secure; samesite=none` • har query par `user_id` filter (IDOR) • `secrets.randbelow` (random nahi) • security headers • rate limits.

### 2.8 Testing  (`tests/conftest.py`)
* `httpx.AsyncClient(transport=ASGITransport(app))` — server chalaye bina poori app test.
* Real Postgres + `TRUNCATE` har test se pehle; sirf network edges fake (`fake_groq`, `fake_embeddings`, `sent_emails`).
* `asyncio_default_test_loop_scope = session` (pytest.ini): warna asyncpg pool alag event loops mein "attached to a different loop" error deta hai.
* **Parity tests** (`test_js_parity.py`): purane JS code ke outputs fixtures mein save, Python unse match karta hai. Is ne 2 asli farq pakde (UTF-16 `length` vs Python code points).

### 2.9 RAG pipeline  (`services/rag_engine.py`) — interview ka favourite
1. **Chunking**: JS/TS files function/class boundary par (brace counting); baqi 60-line windows, 10 overlap.
2. **Embeddings**: Ollama `nomic-embed-text` (768-dim) ya Gemini; vectors JSONB mein.
3. **Retrieval**: cosine similarity (numpy se ek hi matrix multiply) + 0.15 keyword boost.
4. **Diversity cap**: ek file ke zyada chunks sab slots na bhar dein.
5. **Re-rank** (stage 2): chhota LLM top-18 ko 0–10 score deta hai; parse fail ho to vector order par wapas (graceful degradation).
6. **Incremental ingestion**: file ka SHA-256 hash; sirf badli hui files dubara embed.
7. **Measure karo**: `scripts/eval_retrieval.py` (hit-rate). "Mujhe lagta hai achha hai" nahi, "5/6 se 6/6" bolo.

---

## 3. NestJS — concepts

### 3.1 Building blocks  (`app.module.ts`, `auth/*`)
* **Module** = feature ka dibba (controllers + providers). **Controller** = HTTP routes (`@Controller('products')`, `@Get()`). **Provider/Service** = logic (`@Injectable()`).
* **DI container**: constructor mein type likho (`constructor(private prisma: PrismaService)`), Nest khud object de deta hai. `@Global()` module (Prisma, Email) har jagah available.
* Decorators sirf metadata set karte hain; asli kaam guards/pipes/interceptors karte hain.

### 3.2 Request lifecycle — YAAD KARO
```
Request → Middleware → Guards → Interceptors(before) → Pipes → Handler → Interceptors(after) → Exception Filter → Response
```
* **Middleware** (`rate-limit.ts`): Express-style, routing se pehle.
* **Guards** (`common/guards.ts`): *allow ya deny*. Hum ne 3 **global** guards (`APP_GUARD`) rakhe, is order mein: `AuthGuard → CsrfGuard → RolesGuard`.
* **Pipes** (`zod.pipe.ts`): validate/transform input.
* **Filters** (`http-error.filter.ts`): har error ko ek hi shape `{error: "..."}` mein badalta hai.
* **Interceptors**: handler ke aage-peeche (logging, response mapping) — is project mein zarurat nahi padi; interview mein definition zaroor aati hai.

### 3.3 "Secure by default"  (`@Public()`)
Purane Express code mein har route par `requireAuth` lagana yaad rakhna padta tha — bhool gaye to route khula. Ab guard **global** hai; sirf `@Public()` waale routes khule (login, register, healthz, public-chat). Naya route bhoolne par bhi band rahega.

### 3.4 PrismaService  (`prisma/prisma.service.ts`)
`extends PrismaClient`, `onModuleInit → $connect`, `onModuleDestroy → $disconnect`. `enableShutdownHooks()` se SIGTERM par clean disconnect. Rust-free `engineType="client"` + `@prisma/adapter-pg`.

### 3.5 Multi-tenancy  (har `*.service.ts`)
* Har table mein `organizationId`; **har query** `where: { organizationId }`.
* Update/delete **two-step**: pehle `findFirst({id, organizationId})`, phir update by verified id (sequential ids guess ho sakti hain).
* Foreign references bhi check hote hain (kisi aur company ka `categoryId` ya `customerId` nahi lag sakta).
* `test/domain.spec.ts` ka pehla test isi ko tod kar dekhta hai — **isolation test hi is app ka sab se qeemti test hai**.

### 3.6 Transactions aur race conditions  (`inventory.service.ts`, `sales.service.ts`)
Masla: do requests ek saath same stock nikalen. Hal:
```ts
const dec = await tx.inventory.updateMany({
  where: { productId, warehouseId, quantity: { gte: qty } },   // condition SQL ke andar
  data:  { quantity: { decrement: qty } },
});
if (dec.count === 0) throw insufficient();                      // kisi aur ne pehle le liya
```
"Pehle read, phir if, phir write" **race-prone** hai; condition ko UPDATE ke andar rakho (atomic). Test: 10 parallel transfers, stock 5 → exactly 5 kamyab.
Sale complete = stock deduct (warehouse ke hisaab se) + har deduction ka `InventoryTransaction` log; cancel = *usi log se* exactly wapas. Ye **audit-log-driven reversal** pattern hai.

### 3.7 Realtime  (`realtime.gateway.ts`)
Socket.io handshake mein **wohi httpOnly cookie** verify hoti hai; har socket `org:<id>` room mein; event sirf us room ko. Test: company B ka socket A ka event nahi sunta.

### 3.8 Testing  (`test/helpers.ts`)
`Test.createTestingModule({imports:[AppModule]}).overrideProvider(EmailService).useValue(fake)`; supertest se asli HTTP. Gotcha jo mujhe mila: fake ke liye `Proxy` mat banao — wo `.then` bhi return karta hai aur Nest use Promise samajh kar hamesha intezaar karta hai.

---

## 4. Frameworks ka taqabul (interview favourite)

**FastAPI vs Django vs Flask**
* FastAPI: async-first, type hints se validation + auto docs, APIs ke liye. ORM/admin/auth khud jodna padta hai.
* Django: batteries-included (ORM, admin, auth, migrations) — full web apps/CMS. DRF se API; thora bhaari.
* Flask: minimal, sync-first; validation/docs khud.
* Meri choice: AI/LLM APIs (streaming, async I/O) → FastAPI. Admin-heavy product → Django.

**NestJS vs Express vs Fastify**
* Express: minimal, koi structure nahi — chhote apps; bade teams mein har koi alag style.
* Fastify: tez, schema-based; structure phir bhi aap ka.
* NestJS: opinionated (modules, DI, decorators), TypeScript-first, Angular jaisa; bade codebases/teams mein consistency. Andar Express ya Fastify engine ban sakta hai.
* Trade-off: boilerplate aur seekhne ka waqt.

**Prisma vs SQLAlchemy**: Prisma = generated typed client, simple API; SQLAlchemy = zyada powerful/flexible (Core + ORM), Python ka standard.

---

## 5. Aap ke projects ki "bugs found" kahaniyan (interview mein sona hain)

Ye sab asal mein mile (tests/DB se verify hue). **Aisi kahani sunana "maine rewrite kiya" se kai guna behtar hai.**

1. **CodeBox — missing table**: `schema.prisma` mein `InterviewSession` nahi, migration use drop karti hai, magar controller use karta hai → interview endpoints crash. *Kaise pakda*: migrations real Postgres par chala kar `\dt` dekha.
2. **CodeBox — chat memory bug**: "last 30 messages" ke bajaye *pehle* 30 (ASC + take). 30 messages ke baad model recent baat bhool jata.
3. **CodeBox — stale interview**: upsert same row id rakhta hai → purane project ke sawal naye project par.
4. **Nexus — tenant isolation toota hua**: migration ne `DROP CONSTRAINT` kiya magar Prisma ne unique *index* banaya tha → do companies same SKU/e-mail nahi rakh sakti thi. *Kaise pakda*: cross-company test fail hua → `pg_indexes` dekha → fix migration `DROP INDEX IF EXISTS`.
5. Chhote: `/products/abc` → 500 (ab 400), FK delete → 500 (ab 409), upload errors 500 (ab 400/413), HTML injection (user ka name e-mail HTML mein raw).

---

## 6. Interview Q&A (zubani practice)

1. **Express se FastAPI/Nest kyun?** — Contract same rakha (URLs/JSON/cookies/DB), sirf internals badle; parity tests se saabit kiya. FastAPI: Python AI ecosystem + async + auto docs. Nest: structure, DI, guards se secure-by-default.
2. **FastAPI async kaise kaam karta hai? `def` vs `async def`?** — `async def` loop par; `def` threadpool mein. Blocking kaam `async def` mein mat karo; `to_thread`.
3. **Dependency Injection kya hai, FastAPI mein kaise?** — `Depends`; auth/session/params; testing mein override; generator se cleanup.
4. **Password hashing kaise?** — bcrypt cost 12, thread mein, 72-byte limit explicit; OTP bhi hash.
5. **JWT cookie vs localStorage?** — httpOnly cookie XSS se safe; lekin CSRF aata hai → SameSite + double-submit token (Nest) / SameSite=None+Secure aur CORS credentials (FastAPI, cross-site).
6. **CSRF double-submit kaise?** — Do cookies: httpOnly auth + readable csrf; frontend header mein echo; attacker cookie *parh* nahi sakta.
7. **IDOR kya aur kaise roka?** — Har query mein owner/org filter; update se pehle ownership check; param UUID validation; test: doosra user 404 paata hai.
8. **Multi-tenancy kaise?** — Shared DB, `organizationId` har row, har query filter, cross-reference checks, per-tenant unique constraints, isolation tests; AI tools bhi scoped.
9. **Race condition kaise roki?** — Conditional atomic UPDATE (`quantity >= qty`) + transaction; test mein parallel requests.
10. **Transaction kab?** — Jab kai writes ek saath kamyab/nakam hon (sale complete: deduct + log + status). Sale cancel = log se reverse.
11. **Background task limitations?** — Same process; restart par lost; scale ke liye queue + worker; status field (`ragStatus`) se UI ko batate hain.
12. **RAG kya hai? aap ne kaise banaya?** — Sec. 2.9. Hybrid retrieval (vector + keyword) + LLM rerank; incremental ingestion; eval script.
13. **Embeddings/cosine?** — Text ko vector; angle ki closeness = meaning ki closeness; numpy se vectorized.
14. **LLM se JSON na aaye to?** — Fences strip, regex se array nikalo, line-based fallback parser, aakhir mein safe default; kabhi user flow na toote.
15. **Prompt injection / AI safety?** — Tools har query mein org filter; guest ko sirf public data; model ke tool-loop ki hard limit (4 rounds); keys server par.
16. **Rate limiting?** — Fixed window per IP; login par sirf *failed* attempts count; limitation: in-memory → multi-instance mein Redis.
17. **Testing strategy?** — Real DB + fake network edges; e2e + parity + concurrency tests; kya test nahi hua (real Groq) wo bhi batao.
18. **Error handling design?** — Ek error contract; production mein internals leak nahi; `expose` flag sirf safe errors ke liye.
19. **NestJS guards vs middleware?** — Middleware routing se pehle, handler ka pata nahi; guards ko `ExecutionContext`/metadata (`@Roles`) milta hai → authorization ke liye.
20. **Pipes/Filters/Interceptors?** — Sec. 3.2.
21. **Prisma vs raw SQL?** — Prisma productivity/type safety; complex/reporting queries ya bulk ke liye raw/SQLAlchemy Core.
22. **Migrations ka masla?** — Aap ki apni kahani #4: migration ko *test* karo (constraints vs indexes).
23. **Scaling kaise karenge?** — Stateless app, Redis rate-limit/session, queue workers, DB indexes, pgvector (embeddings JSONB ke bajaye), read replicas.
24. **WebSocket auth?** — Handshake mein cookie verify, org room.
25. **Sab se mushkil bug?** — Sec. 5 mein se koi ek, step-by-step (symptom → hypothesis → proof → fix → test).

---

## 7. Aksar poochhe jaane wale "traps"
* "Aap ne ye AI se banwaya?" — Sach bolo: AI-assisted rewrite, **par** aap ko har concept samajh aata hai, tests chalate hain, kahani Sec. 5 se sunao. Jo sawal par na aaye ("mujhe is hisse ka detail yaad nahi, main code khol kar dekhta") — jhoot kabhi nahi.
* CV mein sirf wohi likhein jo aap ne **chalaya aur samjha** hai (neeche Sec. 9).

---

## 8. Practice exercises (har ek 1–2 ghante)
1. FastAPI: `/api/snippets` mein `?q=` search add karo + test likho.
2. FastAPI: `rate_limit_middleware` ko Redis-backed bana do (interface same).
3. FastAPI: `BackgroundTasks` ki jagah ARQ/Celery worker lagao; `ragStatus` flow wahi rakho.
4. FastAPI: `embedding` JSONB → `pgvector` column; retrieval SQL mein.
5. FastAPI: `/api/send_message` ka streaming (SSE) version.
6. NestJS: ek **Interceptor** likho jo har request ka time log kare.
7. NestJS: `Product` ke liye class-validator/Zod DTOs lagao (abhi `any` body hai) — validation messages same rakho.
8. NestJS: Swagger (`@nestjs/swagger`) lagao.
9. NestJS: `GET /sales` par date-range filter + test.
10. Dono: GitHub Actions CI (Postgres service) mein tests chalao.

---

## 9. CV mein kab aur kya likhein (sach ke saath)
Jab aap (a) dono ko apni machine par asli keys ke saath chala len, (b) deploy kar len, (c) Sec. 6 ke jawab de saken — tab:

* **CodeBox (FastAPI)**: "Rebuilt a Node/Express + Prisma backend in FastAPI (async SQLAlchemy, Pydantic v2) with an identical API contract on the same PostgreSQL database; 135 pytest tests incl. parity tests against the original implementation; fixed 9 defects found during the port (e.g. missing InterviewSession table, stale chat context)."
* **Nexus (NestJS)**: "Rebuilt an Express + Prisma multi-tenant inventory API in NestJS (global guards for auth/CSRF/RBAC, Zod pipes, Socket.io gateway); 54 e2e tests on PostgreSQL covering tenant isolation and race conditions; found and fixed a migration defect that kept global unique indexes (cross-tenant SKU/e-mail collisions)."
* Table mein add: **FastAPI, SQLAlchemy, Pydantic, pytest, NestJS, Jest** — jab tak ye dono projects live na hon, Skills mein "(learning)" na likhein; interview mein pakre jaane se behtar hai sach.

---

## 10. Abhi tak verify nahi hua (aap ko khud karna hai)
* Asli **Groq / Ollama / Gemini / Resend** calls (test sandbox mein internet nahi tha — mock the).
* Browser mein **frontend + naya backend** ka end-to-end (login, chat, upload, interview, inventory screens).
* **Deployment** (Render/Railway/Vercel) aur cross-site cookies (CodeBox: `SameSite=None; Secure` + HTTPS zaroori).
* Pehle apni **staging copy DB** par chalao, production par nahi.

Is checklist ke baad mujhe batao — main CV update kar dunga (table + projects entries), 2 pages mein.
