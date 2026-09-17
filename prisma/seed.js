// prisma/seed.js
//
// Creates (or refreshes) the fixed demo account and its sample data.
// Run manually with `npm run seed`, or automatically via `npx prisma db seed`
// after `prisma migrate deploy` on first setup.
//
// Safe to re-run any time — it upserts the demo user and fully resets their
// content back to the curated sample set (see utils/demoUser.js for why
// this project resets the demo account's data rather than using a cron job
// or read-only mode).

const { ensureDemoUserSeeded, DEMO_USER_EMAIL } = require('../utils/demoUser');
const prisma = require('../models/prismaClient');

async function main() {
  console.log('🌱 Seeding demo account...');
  const demoUser = await ensureDemoUserSeeded();
  console.log(`✅ Demo account ready: ${demoUser.email} (id: ${demoUser.id})`);
  console.log(`   Login with DEMO_USER_PASSWORD_SEED from your .env (see .env.example).`);
}

main()
  .catch((err) => {
    console.error('❌ Demo seed failed:', err);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
