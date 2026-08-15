// scripts/test-rag.js
// Standalone RAG pipeline test — NOT wired into the real app yet.
// Run with: node scripts/test-rag.js
//
// What this proves:
//   1. We can turn code text into an embedding (a vector of numbers)
//   2. We can store those vectors in Postgres via Prisma
//   3. We can turn a user's question into an embedding too
//   4. We can find the most relevant chunk using cosine similarity —
//      without sending the WHOLE project to the LLM.

const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();

const OLLAMA_URL = 'http://localhost:11434/api/embeddings';
const EMBED_MODEL = 'nomic-embed-text';
const SESSION_ID = 'test-session-001'; // fake session, just for this experiment

// ── A handful of fake "file chunks" from a pretend project ──────────────
// In the real pipeline these will come from extractProjectFiles() output,
// split into smaller pieces instead of being sent whole.
const sampleChunks = [
  {
    filePath: 'controllers/authController.js',
    content: `
async function loginUser(req, res) {
  const { email, password } = req.body;
  const user = await User.findOne({ email });
  if (!user) return res.status(404).json({ message: 'User not found' });
  const isMatch = await bcrypt.compare(password, user.password);
  if (!isMatch) return res.status(401).json({ message: 'Invalid credentials' });
  const token = jwt.sign({ id: user._id }, process.env.JWT_SECRET);
  res.cookie('token', token, { httpOnly: true });
  res.json({ message: 'Logged in' });
}`.trim(),
  },
  {
    filePath: 'controllers/authController.js',
    content: `
async function registerUser(req, res) {
  const { email, password, name } = req.body;
  const existing = await User.findOne({ email });
  if (existing) return res.status(400).json({ message: 'Email already in use' });
  const hashed = await bcrypt.hash(password, 10);
  const user = await User.create({ email, password: hashed, name });
  res.status(201).json({ message: 'User created', userId: user._id });
}`.trim(),
  },
  {
    filePath: 'utils/priceCalculator.js',
    content: `
function calculateTotal(items, taxRate = 0.05) {
  const subtotal = items.reduce((sum, item) => sum + item.price * item.qty, 0);
  const tax = subtotal * taxRate;
  return { subtotal, tax, total: subtotal + tax };
}`.trim(),
  },
  {
    filePath: 'components/Cart.jsx',
    content: `
function Cart({ items, onRemove }) {
  return (
    <div className="cart">
      {items.map(item => (
        <div key={item.id}>
          {item.name} - \${item.price}
          <button onClick={() => onRemove(item.id)}>Remove</button>
        </div>
      ))}
    </div>
  );
}`.trim(),
  },
];

// ── Step 1: text -> embedding vector, via local Ollama ───────────────────
async function getEmbedding(text) {
  const response = await fetch(OLLAMA_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: EMBED_MODEL, prompt: text }),
  });
  if (!response.ok) {
    throw new Error(`Ollama embedding request failed: ${response.status}`);
  }
  const data = await response.json();
  return data.embedding; // array of 768 numbers
}

// ── Step 2: cosine similarity between two vectors ────────────────────────
// Measures the ANGLE between two vectors, not their distance.
// Result is between -1 (opposite) and 1 (identical direction).
// For embeddings, closer to 1 = more semantically similar.
function cosineSimilarity(a, b) {
  let dot = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

// ── Step 3: ingest — embed each chunk and save to Postgres ──────────────
async function ingestChunks() {
  console.log(`\nIngesting ${sampleChunks.length} chunks...\n`);

  // Clear any previous run of this test session
  await prisma.codeChunk.deleteMany({ where: { sessionId: SESSION_ID } });

  for (const chunk of sampleChunks) {
const embedding = await getEmbedding(`File: ${chunk.filePath}\n${chunk.content}`);
    await prisma.codeChunk.create({
      data: {
        sessionId: SESSION_ID,
        filePath: chunk.filePath,
        content: chunk.content,
        embedding: embedding, // stored as JSON
      },
    });
    console.log(`  ✓ embedded + saved: ${chunk.filePath} (${chunk.content.slice(0, 40)}...)`);
  }
}

// ── Step 4: retrieve — embed the question, compare to all stored chunks ─
async function retrieve(question, topK = 2) {
  console.log(`\nQuestion: "${question}"`);

  const queryEmbedding = await getEmbedding(question);

  const allChunks = await prisma.codeChunk.findMany({
    where: { sessionId: SESSION_ID },
  });

  const scored = allChunks.map((chunk) => ({
    filePath: chunk.filePath,
    content: chunk.content,
    score: cosineSimilarity(queryEmbedding, chunk.embedding),
  }));

  scored.sort((a, b) => b.score - a.score);

  console.log(`\nTop ${topK} most relevant chunks:\n`);
  scored.slice(0, topK).forEach((result, i) => {
    console.log(`${i + 1}. [score: ${result.score.toFixed(4)}] ${result.filePath}`);
    console.log(`   ${result.content.split('\n')[0]}...\n`);
  });
}

// ── Run the full pipeline ─────────────────────────────────────────────
async function main() {
  await ingestChunks();

  // This should clearly match the login function chunk, not the cart or price ones.
  await retrieve('how does user login work?');

  // This should clearly match the price calculator chunk.
  await retrieve('where is tax calculated?');

  await prisma.$disconnect();
}

main().catch((err) => {
  console.error('RAG test failed:', err);
  process.exit(1);
});