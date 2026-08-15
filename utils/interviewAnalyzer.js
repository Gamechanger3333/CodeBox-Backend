// utils/interviewAnalyzer.js
//
// Interview Prep — generates a mock technical interview grounded in the
// user's own uploaded project (not generic LeetCode-style questions).
// Reuses buildProjectContext from projectAnalyzer.js so there is exactly
// one place that turns { fileTree, files } into prompt text.
//
// Three AI calls, each with a narrow job:
//   1. generateInterviewQuestions — read the project once, produce a fixed
//      list of categorized questions (cheap: runs once per project upload)
//   2. evaluateAnswer            — grade one answer + ask one follow-up
//      (runs once per question the user answers)
//   3. generateFinalReport        — read the whole transcript, produce a
//      weakness summary (runs once, at the end)
//
// Splitting it this way keeps each prompt short and each AI call cheap —
// important on Groq's free tier, which has a tokens-per-minute limit.

const groq = require('./groqClient');
const { buildProjectContext } = require('./projectAnalyzer');

const QUESTION_CATEGORIES = [
  'architecture',   // why this structure, what alternatives existed
  'scaling',        // what breaks at 10x / 100x / 1000x load
  'security',       // auth, input validation, secrets, injection
  'debugging',      // production incident walk-throughs
  'tradeoffs',      // what was sacrificed for what
  'dependencies',   // why these libraries, what they cost you
];

const NUM_QUESTIONS = 12; // 2 per category, roughly — enough for a real mock interview without being exhausting

const INTERVIEWER_SYSTEM_PROMPT = `You are a senior staff engineer conducting a technical interview at a top tech company (Google/Amazon/Microsoft-caliber bar). You have been given a candidate's real project to interview them about — not abstract trivia.

YOUR STYLE:
- Ask the way real interviewers do: specific, grounded in the actual code you were shown, not generic textbook questions.
- Reference actual file names, libraries, and patterns from the project when relevant.
- Be rigorous but fair — you're trying to find the edges of the candidate's understanding, not trick them.
- Cover both breadth (does the candidate understand the whole system) and depth (can they go deep on one decision).`;

/**
 * Generates a fixed set of interview questions from the project context.
 * Runs once, right after a project is uploaded (or when interview prep is
 * first opened for an already-uploaded project).
 */
exports.generateInterviewQuestions = async (fileTree, files) => {
  const projectContext = buildProjectContext(fileTree, files);

  const prompt = `${projectContext}

---

Based on this project, generate exactly ${NUM_QUESTIONS} realistic technical interview questions a senior interviewer would ask the person who built this. Spread them across these categories: ${QUESTION_CATEGORIES.join(', ')}.

Requirements for each question:
- Reference something SPECIFIC from this project (an actual file, library, pattern, or design choice you can see in the code) — never a generic question that could apply to any project.
- Push toward production reality: failure modes, scale, security, trade-offs — not just "explain how this works."
- Vary difficulty: include a few foundational questions and a few that require real depth.

Respond with ONLY a JSON array, no other text, in exactly this format:
[
  { "category": "architecture", "question": "..." },
  { "category": "scaling", "question": "..." }
]`;

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages: [
      { role: 'system', content: INTERVIEWER_SYSTEM_PROMPT },
      { role: 'user', content: prompt },
    ],
    temperature: 0.6,
    max_tokens: 2000,
  });

  const raw = completion.choices[0]?.message?.content || '[]';
  return parseQuestionsJSON(raw);
};

/**
 * Robustly parses the model's JSON response. LLMs occasionally wrap JSON
 * in markdown fences or add a stray sentence despite instructions — this
 * extracts the JSON array regardless, and falls back to a safe minimal
 * question set rather than crashing the whole upload flow if parsing
 * still fails (a bad interview-question batch shouldn't break the
 * project upload the user actually asked for).
 */
function parseQuestionsJSON(raw) {
  const cleaned = raw.replace(/```json|```/g, '').trim();
  const match = cleaned.match(/\[[\s\S]*\]/);
  const jsonText = match ? match[0] : cleaned;

  try {
    const parsed = JSON.parse(jsonText);
    if (!Array.isArray(parsed) || parsed.length === 0) throw new Error('Empty or invalid array');
    return parsed
      .filter(q => q && typeof q.question === 'string' && q.question.trim())
      .map((q, i) => ({
        id: `q${i + 1}`,
        category: QUESTION_CATEGORIES.includes(q.category) ? q.category : 'architecture',
        question: q.question.trim(),
      }));
  } catch (err) {
    console.error('Failed to parse interview questions JSON:', err.message);
    return [{
      id: 'q1',
      category: 'architecture',
      question: 'Walk me through how this project is structured, and why you organized it that way.',
    }];
  }
}

/**
 * Evaluates one answer and produces a follow-up question, the way a real
 * interviewer would react in the moment — not a detached grade.
 */
exports.evaluateAnswer = async (fileTree, files, question, userAnswer, transcriptSoFar) => {
  const projectContext = buildProjectContext(fileTree, files);

  const transcriptText = transcriptSoFar.length
    ? transcriptSoFar.map(t => `Q: ${t.question}\nA: ${t.answer}`).join('\n\n')
    : '(this is the first question)';

  const prompt = `${projectContext}

---

INTERVIEW SO FAR:
${transcriptText}

---

CURRENT QUESTION: ${question}

CANDIDATE'S ANSWER: ${userAnswer}

---

Respond as the interviewer would, in three parts:

1. FOLLOW_UP: Ask one realistic, probing follow-up question based specifically on what the candidate just said — the way a real interviewer would push deeper on a specific claim, assumption, or gap in their answer. If their answer was strong and complete, your follow-up can raise a harder edge case or a scaling/production angle instead.

2. FEEDBACK: 2-4 sentences of honest, specific feedback on the answer itself — what was strong, what was missing or hand-wavy, and what a stronger answer would have included. Be direct, the way a good mentor would be, not falsely encouraging.

3. TEACH: 1-2 sentences explaining the underlying concept being tested, so the candidate learns something even if they already answered well.

Respond with ONLY valid JSON, no other text, in exactly this format:
{ "followUp": "...", "feedback": "...", "teach": "..." }`;

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages: [
      { role: 'system', content: INTERVIEWER_SYSTEM_PROMPT },
      { role: 'user', content: prompt },
    ],
    temperature: 0.5,
    max_tokens: 800,
  });

  const raw = completion.choices[0]?.message?.content || '{}';
  return parseEvaluationJSON(raw);
};

function parseEvaluationJSON(raw) {
  const cleaned = raw.replace(/```json|```/g, '').trim();
  const match = cleaned.match(/\{[\s\S]*\}/);
  const jsonText = match ? match[0] : cleaned;

  try {
    const parsed = JSON.parse(jsonText);
    return {
      followUp: typeof parsed.followUp === 'string' ? parsed.followUp.trim() : "Let's move to the next question.",
      feedback: typeof parsed.feedback === 'string' ? parsed.feedback.trim() : '',
      teach: typeof parsed.teach === 'string' ? parsed.teach.trim() : '',
    };
  } catch (err) {
    console.error('Failed to parse evaluation JSON:', err.message);
    return {
      followUp: "Let's move to the next question.",
      feedback: 'Could not generate detailed feedback for this answer — moving on.',
      teach: '',
    };
  }
}

/**
 * Generates the final weakness report after the interview is complete —
 * reads the full transcript and surfaces patterns, not just a recap of
 * each individual answer.
 */
exports.generateFinalReport = async (fileTree, files, transcript) => {
  const projectContext = buildProjectContext(fileTree, files);

  const transcriptText = transcript
    .map((t, i) => `Q${i + 1} [${t.category}]: ${t.question}\nAnswer: ${t.answer}\nInterviewer feedback: ${t.feedback || '(none)'}`)
    .join('\n\n');

  const prompt = `${projectContext}

---

FULL INTERVIEW TRANSCRIPT:
${transcriptText}

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
Concrete topics/concepts to study, tied directly to the weak areas — not generic interview advice.`;

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages: [
      { role: 'system', content: INTERVIEWER_SYSTEM_PROMPT },
      { role: 'user', content: prompt },
    ],
    temperature: 0.4,
    max_tokens: 1800,
  });

  return completion.choices[0]?.message?.content || 'Could not generate report.';
};
