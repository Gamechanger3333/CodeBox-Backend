// scripts/test-multitenancy.js
// Verifies that CodeChunk data is properly isolated by sessionId — i.e.
// User A's retrieval results NEVER include User B's project content.
// This matters a lot here: askProject only filters by `sessionId: String(userId)`,
// so a bug in that filter (or a missing WHERE clause anywhere) would leak
// one user's private code into another user's chat responses.
//
// Run with: node scripts/test-multitenancy.js

const { PrismaClient } = require('@prisma/client');
const { retrieveRelevantChunks } = require('../utils/ragEngine');
const prisma = new PrismaClient();

const USER_A = 'test-tenant-A';
const USER_B = 'test-tenant-B';

async function seedFakeTenant(sessionId, secretMarker) {
  // Each tenant gets one very distinctive, unique chunk (the "secretMarker")
  // that should NEVER show up for the other tenant, no matter what they ask.
  await prisma.codeChunk.deleteMany({ where: { sessionId } });
  await prisma.codeChunk.create({
    data: {
      sessionId,
      filePath: 'secrets/config.js',
      content: `const API_KEY = "${secretMarker}"; // this is ${sessionId}'s private data`,
      embedding: await require('../utils/ragEngine').getEmbedding(
        `File: secrets/config.js\nconst API_KEY = "${secretMarker}";`
      ),
    },
  });
}

async function runTest() {
  console.log('Seeding two isolated fake tenants...\n');
  await seedFakeTenant(USER_A, 'SECRET_MARKER_ALPHA_9182');
  await seedFakeTenant(USER_B, 'SECRET_MARKER_BETA_4477');

  console.log('Querying as User A, asking about the API key / secret config...');
  const resultsForA = await retrieveRelevantChunks(USER_A, 'what is the API key in the config?', 5, { useReranking: false });

  console.log('Querying as User B, asking the same question...');
  const resultsForB = await retrieveRelevantChunks(USER_B, 'what is the API key in the config?', 5, { useReranking: false });

  const aLeakedIntoB = resultsForB.some((r) => r.content.includes('SECRET_MARKER_ALPHA_9182'));
  const bLeakedIntoA = resultsForA.some((r) => r.content.includes('SECRET_MARKER_BETA_4477'));
  const aGotOwnData = resultsForA.some((r) => r.content.includes('SECRET_MARKER_ALPHA_9182'));
  const bGotOwnData = resultsForB.some((r) => r.content.includes('SECRET_MARKER_BETA_4477'));

  console.log('\n=== Results ===');
  console.log(aGotOwnData ? '✅ User A retrieved their own data' : '⚠️  User A could not retrieve their own data (unrelated issue)');
  console.log(bGotOwnData ? '✅ User B retrieved their own data' : '⚠️  User B could not retrieve their own data (unrelated issue)');
  console.log(!aLeakedIntoB ? '✅ PASS: User A\'s secret did NOT leak into User B\'s results' : '❌ FAIL: DATA LEAK — User A\'s secret appeared in User B\'s results!');
  console.log(!bLeakedIntoA ? '✅ PASS: User B\'s secret did NOT leak into User A\'s results' : '❌ FAIL: DATA LEAK — User B\'s secret appeared in User A\'s results!');

  const isolationSecure = !aLeakedIntoB && !bLeakedIntoA;
  console.log(`\n${isolationSecure ? '🔒 Multi-tenancy isolation: SECURE' : '🚨 Multi-tenancy isolation: VULNERABLE — fix before any real deployment'}`);

  // Cleanup — don't leave fake test data sitting in the database
  await prisma.codeChunk.deleteMany({ where: { sessionId: USER_A } });
  await prisma.codeChunk.deleteMany({ where: { sessionId: USER_B } });
  await prisma.$disconnect();
}

runTest().catch((err) => {
  console.error('Test failed to run:', err);
  process.exit(1);
});