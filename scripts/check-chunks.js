// scripts/check-chunks.js
// Quick diagnostic: list which files got chunked & embedded for a given
// session, optionally filtered by a keyword in the file path.
//
// Run with: node scripts/check-chunks.js stripe

const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();

const SESSION_ID = '1'; // change if your test user id is different
const filterKeyword = process.argv[2] || ''; // e.g. "stripe"

async function main() {
  const allChunks = await prisma.codeChunk.findMany({
    where: { sessionId: SESSION_ID },
    select: { filePath: true },
  });

  const uniqueFiles = [...new Set(allChunks.map((c) => c.filePath))];

  console.log(`Total chunks in DB for session "${SESSION_ID}": ${allChunks.length}`);
  console.log(`Unique files represented: ${uniqueFiles.length}\n`);

  if (filterKeyword) {
    const matches = uniqueFiles.filter((f) =>
      f.toLowerCase().includes(filterKeyword.toLowerCase())
    );
    console.log(`Files matching "${filterKeyword}": ${matches.length}`);
    matches.forEach((f) => console.log(' -', f));
    if (matches.length === 0) {
      console.log(`\n⚠️  No chunks found for "${filterKeyword}" — this file was likely`);
      console.log(`   never ingested (skipped during extraction), not a retrieval bug.`);
    }
  } else {
    console.log('All unique files in the index:');
    uniqueFiles.forEach((f) => console.log(' -', f));
  }

  await prisma.$disconnect();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});