// scripts/eval-retrieval.js
// Evaluates retrieval quality: for a set of questions with KNOWN correct
// answers (which file should be retrieved), check if our retrieval
// actually finds them. This is how you move from "it seems to work"
// to "I measured that it works 80% of the time".
//
// Run with: node scripts/eval-retrieval.js
// (Run this AFTER uploading a project through the app, so CodeChunk
//  table already has data for your test user.)

const { retrieveRelevantChunks } = require('../utils/ragEngine');

const USER_ID = 1; // change to your actual test user's id

// ── The "answer key" ─────────────────────────────────────────────────────
// For each question, YOU manually decide (by reading the code) which
// file(s) SHOULD show up in the results. Be specific — this is the
// ground truth you're testing against.
const testCases = [
  {
    question: 'how does user login and authentication work?',
    expectedFilePathIncludes: 'authMiddleware',
  },
  {
    question: 'how is the database connection configured?',
    expectedFilePathIncludes: 'database',
  },
  {
    question: 'how are courses fetched or managed?',
    expectedFilePathIncludes: 'course', // matches coursesRoutes.js / coursesModel.js
  },
  {
    question: 'how is an assignment created?',
    expectedFilePathIncludes: 'assignment', // matches assignmentController.js / assignmentModel.js
  },
  {
    question: 'how are teacher profiles handled?',
    expectedFilePathIncludes: 'teacherProfile',
  },
  {
    question: 'how does the app handle payments or subscriptions?',
    expectedFilePathIncludes: 'stripe', // matches stripeModel.js / stripeRoutes.js
  },
];

async function evaluate() {
  console.log(`Running ${testCases.length} retrieval test cases...\n`);

  let passed = 0;

  for (const test of testCases) {
    const results = await retrieveRelevantChunks(USER_ID, test.question, 5);

    const found = results.some((r) =>
      r.filePath.toLowerCase().includes(test.expectedFilePathIncludes.toLowerCase())
    );

    const status = found ? '✅ PASS' : '❌ FAIL';
    if (found) passed++;

    console.log(`${status} — "${test.question}"`);
    console.log(`   expected filePath to include: "${test.expectedFilePathIncludes}"`);
    console.log(`   top result: ${results[0]?.filePath ?? 'none'} (score: ${results[0]?.score.toFixed(3) ?? 'n/a'})`);
    console.log(`   all retrieved: ${results.map(r => r.filePath).join(', ')}\n`);
  }

  const accuracy = ((passed / testCases.length) * 100).toFixed(1);
  console.log(`\n=== Result: ${passed}/${testCases.length} passed (${accuracy}% accuracy) ===`);
}

evaluate().catch((err) => {
  console.error('Evaluation failed:', err);
  process.exit(1);
});