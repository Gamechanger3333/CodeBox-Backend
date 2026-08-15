// scripts/test-caching.js
// Directly tests the incremental ingestion logic, bypassing the frontend's
// "Clear project" requirement — calls ingestProjectChunks twice with the
// SAME content and confirms the second call skips everything.
//
// Run with: node scripts/test-caching.js

const { ingestProjectChunks } = require('../utils/ragEngine');

const TEST_SESSION_ID = 'test-caching-session';

const sampleFiles = [
  { path: 'a.js', content: 'function a() { return 1; }' },
  { path: 'b.js', content: 'function b() { return 2; }' },
  { path: 'c.js', content: 'function c() { return 3; }' },
];

async function run() {
  console.log('--- First ingestion (should embed all files) ---');
  const first = await ingestProjectChunks(TEST_SESSION_ID, sampleFiles);
  console.log('Result:', first);

  console.log('\n--- Second ingestion, IDENTICAL content (should skip all files) ---');
  const second = await ingestProjectChunks(TEST_SESSION_ID, sampleFiles);
  console.log('Result:', second);

  console.log('\n--- Third ingestion, ONE file changed (should embed only that one) ---');
  const modifiedFiles = [
    ...sampleFiles.slice(0, 2),
    { path: 'c.js', content: 'function c() { return 999; } // changed!' },
  ];
  const third = await ingestProjectChunks(TEST_SESSION_ID, modifiedFiles);
  console.log('Result:', third);

  const cachingWorks = second.changedFileCount === 0 && second.skippedFileCount === 3;
  const partialUpdateWorks = third.changedFileCount === 1 && third.skippedFileCount === 2;

  console.log('\n=== Summary ===');
  console.log(cachingWorks ? '✅ PASS: unchanged files were correctly skipped' : '❌ FAIL: caching did not skip unchanged files');
  console.log(partialUpdateWorks ? '✅ PASS: only the changed file was re-embedded' : '❌ FAIL: partial update did not isolate the changed file');

  // Cleanup
  const { PrismaClient } = require('@prisma/client');
  const prisma = new PrismaClient();
  await prisma.codeChunk.deleteMany({ where: { sessionId: TEST_SESSION_ID } });
  await prisma.ingestedFileHash.deleteMany({ where: { sessionId: TEST_SESSION_ID } });
  await prisma.$disconnect();
}

run().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});