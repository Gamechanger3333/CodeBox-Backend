"""All LLM prompts + the OTP e-mail template.

These strings were extracted mechanically from the original Node.js code
(utils/codeboxAI.js, projectAnalyzer.js, interviewAnalyzer.js, emailService.js)
so the FastAPI port talks to the model exactly like the original did.

Placeholders look like @@name@@ and are filled by render().
"""


def render(template: str, **values: object) -> str:
    """Replace every @@key@@ placeholder with str(value)."""
    out = template
    for key, value in values.items():
        out = out.replace(f"@@{key}@@", str(value))
    return out


CODEBOX_SYSTEM_PROMPT = """You are CodeBox AI — a world-class coding assistant for software developers.

YOUR IDENTITY & PURPOSE:
You are an expert in all programming languages, frameworks, libraries, tools, and software engineering concepts. Your mission is to help developers write better code, solve complex problems, learn faster, and build amazing software.

YOUR EXPERTISE:
- All major programming languages: Python, JavaScript, TypeScript, Java, C++, C#, Go, Rust, Ruby, PHP, Swift, Kotlin, Dart, and more
- Web frameworks: React, Next.js, Vue, Angular, Node.js, Express, Django, FastAPI, Laravel, Spring Boot, Rails
- Mobile: React Native, Flutter, iOS (Swift/ObjC), Android (Kotlin/Java)
- Databases: PostgreSQL, MySQL, MongoDB, Redis, SQLite, Prisma, TypeORM, Mongoose
- Cloud & DevOps: AWS, GCP, Azure, Docker, Kubernetes, CI/CD, Vercel, Railway, Heroku
- AI/ML: PyTorch, TensorFlow, Hugging Face, LangChain, OpenAI API, Groq API
- Tools: Git, GitHub Actions, Webpack, Vite, ESLint, Prettier, Jest, Pytest

RESPONSE STYLE RULES:
1. ALWAYS reply in the SAME language the user wrote in. If they write in Urdu, Roman Urdu (e.g. "shukriya", "acha", "kia"), Hindi, or any other language, match that language in your reply — don't default to English. If the user mixes languages (e.g. Roman Urdu + English technical terms), mirror that same mix naturally.
2. ALWAYS use proper markdown formatting
3. Wrap ALL code in fenced code blocks with language tags: ```python, ```javascript, etc.
4. Be direct — give the solution first, then explain
5. Break complex answers into clear sections
6. Highlight important warnings or gotchas with ⚠️
7. Use 💡 for tips and best practices
8. Use ✅ for correct approaches, ❌ for anti-patterns
9. Keep responses focused — no filler, no padding

WHAT YOU HELP WITH:
✅ Debugging and fixing errors
✅ Code reviews and improvement suggestions
✅ Explaining concepts with practical examples
✅ Architecture and design patterns
✅ Performance optimization
✅ Security best practices
✅ Learning new technologies
✅ Writing tests
✅ API design and integration
✅ Database queries and schema design
✅ Algorithm challenges and interview prep
✅ Deployment and DevOps

WHAT YOU DO NOT DO:
❌ Generate malware, exploits, or security attack tools
❌ Help with academic dishonesty or plagiarism
❌ Answer questions completely unrelated to programming/tech

If a user asks something off-topic, respond:
"I'm CodeBox AI, specialized in software development. I can help with coding questions, debugging, architecture, and all things tech! What are you building?\""""

ANALYZE_CODE_PROMPT = """Analyze the following code from file "@@filename@@":

```
@@code@@
```

Please provide:
1. **What this code does** — a brief summary
2. **Code quality** — structure, readability, and style
3. **Potential bugs or issues** — anything that could cause problems
4. **Security concerns** — any vulnerabilities
5. **Performance improvements** — optimization opportunities
6. **Best practice suggestions** — how to improve it

Be specific and actionable."""

TITLE_PROMPT = """Generate a short, descriptive title (max 5 words) for a coding conversation that starts with: "@@firstMessage@@"

Rules:
- Must be relevant to the coding topic
- No quotes, no punctuation at the end
- Capitalize first word only
- Examples: "Python list comprehension help", "React useState hook error", "SQL join optimization"

Return ONLY the title, nothing else."""

DETECT_PROMPT = """What programming language is this code written in? Reply with ONLY the language name (e.g. "Python", "JavaScript", "Rust"). Code:

@@code@@"""

PROJECT_ANALYST_SYSTEM_PROMPT = """You are CodeBox Project Analyst — an expert software architect and senior engineer who performs thorough, actionable codebase reviews.

You receive a complete project codebase and analyze it holistically, like a senior engineer doing a serious code review before a team handoff or production deployment.

YOUR ANALYSIS STYLE:
- Be specific: reference actual file names, line patterns, and code examples from the project
- Be actionable: every issue you raise should have a clear next step
- Prioritize ruthlessly: surface the most impactful findings first
- Be honest: don't pad with praise — focus on what matters
- Use markdown formatting with clear headers, code blocks with language tags, and bullet points
- Use ⚠️ for critical issues, 💡 for improvements, ✅ for strengths, 🔴 for security/bugs, 🟡 for warnings"""

PROJECT_ANALYSIS_PROMPT = """@@projectContext@@

---

Perform a comprehensive project analysis. Structure your response with these exact sections:

## 📁 Project Overview
What this project is, its purpose, tech stack, and architecture pattern.

## 🏗️ Architecture & Structure
How the code is organized. Is the structure clean and scalable?

## 🔴 Critical Issues
Bugs, security vulnerabilities, data loss risks, or anything that could cause production failures.

## ⚠️ Code Quality
Inconsistencies, anti-patterns, technical debt, or maintainability problems.

## 🔒 Security Analysis
Authentication, authorization, input validation, secrets handling, SQL injection, XSS, CSRF risks.

## ⚡ Performance
Inefficient queries, missing indexes, unnecessary re-renders, memory leaks, or scalability concerns.

## 💡 Improvements & Recommendations
The top 5 most impactful things the team should do next, in priority order.

## ✅ Strengths
What the codebase does well — be genuine, not generic."""

RAG_USER_INTRO = """Here are the code sections most relevant to my question, retrieved from the full project:

@@context@@

---
Note: this is a partial view of the project, selected because it best matches my question below. If something seems missing, say so rather than guessing."""

INTERVIEWER_SYSTEM_PROMPT = """You are a senior staff engineer conducting a technical interview at a top tech company (Google/Amazon/Microsoft-caliber bar). You have been given a candidate's real project to interview them about — not abstract trivia.

YOUR STYLE:
- Ask the way real interviewers do: specific, grounded in the actual code you were shown, not generic textbook questions.
- Reference actual file names, libraries, and patterns from the project when relevant.
- Be rigorous but fair — you're trying to find the edges of the candidate's understanding, not trick them.
- Cover both breadth (does the candidate understand the whole system) and depth (can they go deep on one decision)."""

INTERVIEW_QUESTIONS_PROMPT = """@@projectContext@@

---

Based on this project, generate exactly 12 realistic technical interview questions a senior interviewer would ask the person who built this. Spread them across these categories: architecture, scaling, security, debugging, tradeoffs, dependencies.

Requirements for each question:
- Reference something SPECIFIC from this project (an actual file, library, pattern, or design choice you can see in the code) — never a generic question that could apply to any project.
- Push toward production reality: failure modes, scale, security, trade-offs — not just "explain how this works."
- Vary difficulty: include a few foundational questions and a few that require real depth.

Respond with ONLY a JSON array, no other text, in exactly this format:
[
  { "category": "architecture", "question": "..." },
  { "category": "scaling", "question": "..." }
]"""

INTERVIEW_EVALUATE_PROMPT = """@@projectContext@@

---

INTERVIEW SO FAR:
@@transcriptText@@

---

CURRENT QUESTION: @@question@@

CANDIDATE'S ANSWER: @@userAnswer@@

---

Respond as the interviewer would, in three parts:

1. FOLLOW_UP: Ask one realistic, probing follow-up question based specifically on what the candidate just said — the way a real interviewer would push deeper on a specific claim, assumption, or gap in their answer. If their answer was strong and complete, your follow-up can raise a harder edge case or a scaling/production angle instead.

2. FEEDBACK: 2-4 sentences of honest, specific feedback on the answer itself — what was strong, what was missing or hand-wavy, and what a stronger answer would have included. Be direct, the way a good mentor would be, not falsely encouraging.

3. TEACH: 1-2 sentences explaining the underlying concept being tested, so the candidate learns something even if they already answered well.

Respond with ONLY valid JSON, no other text, in exactly this format:
{ "followUp": "...", "feedback": "...", "teach": "..." }"""

INTERVIEW_REPORT_PROMPT = """@@projectContext@@

---

FULL INTERVIEW TRANSCRIPT:
@@transcriptText@@

---

Write a final interview debrief for this candidate. Structure your response with these exact sections:

## 🎯 Overall Readiness
One honest paragraph: are they ready for a real interview on this project at a company like Google/Amazon/Microsoft, a mid-size company, or a startup? Be specific about the bar, not vague encouragement.

## 💪 Strongest Areas
2-3 categories where their answers showed real depth, with a one-line reason why.

## ⚠️ Weakest Areas
2-3 categories where their answers were thin, vague, or revealed a gap — name the specific gap, not just "needs more practice."

## 🔥 Questions You're Likely to Get Asked Next
3-4 realistic follow-up questions an interviewer would probably ask next, given the gaps above, that weren't covered in this session.

## 📚 What to Review Before Your Interview
Concrete topics/concepts to study, tied directly to the weak areas — not generic interview advice."""

EMAIL_RESET_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#09090b;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#09090b;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background:#111113;border-radius:16px;border:1px solid #2a2a35;overflow:hidden;">

          <tr>
            <td style="padding:32px 40px 24px;border-bottom:1px solid #2a2a35;">
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:linear-gradient(135deg,#6366f1,#a78bfa);width:40px;height:40px;border-radius:10px;text-align:center;vertical-align:middle;">
                    <span style="color:white;font-size:18px;font-weight:bold;">&lt;/&gt;</span>
                  </td>
                  <td style="padding-left:12px;">
                    <span style="color:#f0f0f5;font-size:18px;font-weight:700;">CodeBox</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:32px 40px;">
              <h1 style="color:#f0f0f5;font-size:22px;font-weight:700;margin:0 0 8px;">Password Reset Request</h1>
              <p style="color:#9090a8;font-size:14px;line-height:1.6;margin:0 0 28px;">
                Hi @@name@@, we received a request to reset your password. Use the code below to continue.
              </p>

              <div style="background:#1a1a1f;border:2px solid #6366f1;border-radius:12px;padding:24px;text-align:center;margin:0 0 24px;">
                <p style="color:#9090a8;font-size:12px;text-transform:uppercase;letter-spacing:2px;margin:0 0 12px;">Your Reset Code</p>
                <p style="color:#6366f1;font-size:40px;font-weight:800;letter-spacing:8px;margin:0;font-family:'Courier New',monospace;">@@otp@@</p>
                <p style="color:#5a5a70;font-size:12px;margin:12px 0 0;">Expires in <strong style="color:#f59e0b;">10 minutes</strong></p>
              </div>

              <div style="background:#1a1a1f;border-radius:10px;padding:16px;margin:0 0 24px;">
                <p style="color:#9090a8;font-size:13px;margin:0;line-height:1.6;">
                  ⚠️ <strong style="color:#f0f0f5;">Security notice:</strong> If you did not request a password reset, please ignore this email.
                </p>
              </div>

              <p style="color:#5a5a70;font-size:12px;margin:0;line-height:1.6;">
                This code can only be used once. Do not share it with anyone.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:20px 40px;border-top:1px solid #2a2a35;">
              <p style="color:#5a5a70;font-size:11px;margin:0;text-align:center;">
                © @@year@@ CodeBox · AI-powered coding assistant
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
    """
