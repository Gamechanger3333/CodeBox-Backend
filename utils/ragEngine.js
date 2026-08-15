// utils/ragEngine.js
// Core RAG building blocks: chunk files -> embed -> store -> retrieve.
// This replaces "dump the whole project into the prompt" with
// "find and send only the chunks relevant to the question".

const prisma = require('../models/prismaClient');

const OLLAMA_URL = 'http://localhost:11434/api/embeddings';
const EMBED_MODEL = 'nomic-embed-text';

// ─────────────────────────────────────────────────────────────────────────
// 1. Chunking
// ─────────────────────────────────────────────────────────────────────────
const CHUNK_LINES = 60;   // fallback: lines per chunk for non-code / no-boundary files
const CHUNK_OVERLAP = 10; // fallback: overlap between consecutive line-chunks
const MAX_FUNCTION_CHUNK_LINES = 120; // a single function bigger than this still gets split
const MIN_STANDALONE_CHUNK_LINES = 4; // blocks smaller than this get merged into neighbors

const JS_FAMILY_EXTENSIONS = new Set(['js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs']);

// Lines that plausibly START a top-level block worth its own chunk:
// named functions, arrow functions assigned to a name, classes, and
// exports.xxx = ... patterns (common in this project's controllers).
const BLOCK_START_PATTERNS = [
  /^\s*(export\s+)?(async\s+)?function\s+\w+/,
  /^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?\(?.*\)?\s*=>/,
  /^\s*(export\s+)?class\s+\w+/,
  /^\s*exports\.\w+\s*=\s*(async\s*)?function/,
  /^\s*exports\.\w+\s*=\s*(async\s*)?\(/,
  /^\s*router\.(get|post|put|patch|delete|use)\s*\(/,
];

function isBlockStart(line) {
  return BLOCK_START_PATTERNS.some((pattern) => pattern.test(line));
}

// Naive brace counter — good enough for finding a block's extent in
// typical formatted code. Doesn't handle braces inside strings/comments/
// template literals perfectly, but errs toward over-including rather
// than cutting a function in half, which is the safer failure mode here.
function countBraceDelta(line) {
  let delta = 0;
  for (const ch of line) {
    if (ch === '{') delta++;
    if (ch === '}') delta--;
  }
  return delta;
}

function splitIntoLineWindows(lines, filePath) {
  const chunks = [];
  if (lines.length <= CHUNK_LINES) {
    return [{ filePath, content: lines.join('\n') }];
  }
  let start = 0;
  while (start < lines.length) {
    const end = Math.min(start + CHUNK_LINES, lines.length);
    chunks.push({ filePath, content: lines.slice(start, end).join('\n') });
    if (end === lines.length) break;
    start = end - CHUNK_OVERLAP;
  }
  return chunks;
}

// Boundary-aware chunking for JS-family files: walk the file, and whenever
// a line looks like the start of a function/class/route handler, capture
// from there until its braces close (depth returns to 0). Everything in
// between named blocks (imports, top-level consts) gets grouped too, so
// no code is silently dropped.
function chunkByBoundaries(content, filePath) {
  const lines = content.split('\n');
  const rawBlocks = [];
  let i = 0;

  while (i < lines.length) {
    if (isBlockStart(lines[i])) {
      const blockLines = [lines[i]];
      let depth = countBraceDelta(lines[i]);
      let j = i + 1;
      // Keep consuming lines until braces balance back to 0 (or file ends).
      // If the block-start line had no '{' at all (rare, e.g. a one-liner
      // arrow function without braces), depth stays 0 and we just take that line.
      while (depth > 0 && j < lines.length) {
        blockLines.push(lines[j]);
        depth += countBraceDelta(lines[j]);
        j++;
      }
      rawBlocks.push({ type: 'block', lines: blockLines });
      i = j;
    } else {
      // Collect consecutive non-block lines (imports, comments, top-level code)
      const looseLines = [lines[i]];
      let j = i + 1;
      while (j < lines.length && !isBlockStart(lines[j])) {
        looseLines.push(lines[j]);
        j++;
      }
      rawBlocks.push({ type: 'loose', lines: looseLines });
      i = j;
    }
  }

  // Merge tiny blocks into the next one so we don't end up with a chunk
  // that's just "}" or a single import line.
  const merged = [];
  for (const block of rawBlocks) {
    const prev = merged[merged.length - 1];
    if (prev && prev.lines.length < MIN_STANDALONE_CHUNK_LINES) {
      prev.lines.push(...block.lines);
    } else {
      merged.push({ lines: [...block.lines] });
    }
  }

  // Split any block that's still too large (e.g. one giant function).
  const chunks = [];
  for (const block of merged) {
    if (block.lines.length > MAX_FUNCTION_CHUNK_LINES) {
      chunks.push(...splitIntoLineWindows(block.lines, filePath));
    } else if (block.lines.length > 0) {
      chunks.push({ filePath, content: block.lines.join('\n') });
    }
  }

  return chunks;
}

function chunkFile(file) {
  const ext = file.path.split('.').pop().toLowerCase();

  if (JS_FAMILY_EXTENSIONS.has(ext)) {
    const chunks = chunkByBoundaries(file.content, file.path);
    if (chunks.length > 0) return chunks;
    // If boundary detection found nothing usable (e.g. unusual file), fall through.
  }

  return splitIntoLineWindows(file.content.split('\n'), file.path);
}

function chunkAllFiles(files) {
  const allChunks = [];
  for (const file of files) {
    allChunks.push(...chunkFile(file));
  }
  return allChunks;
}

// ─────────────────────────────────────────────────────────────────────────
// 2. Embedding — text -> vector, via local Ollama.
//    We prefix with the file path: it gives the embedding model useful
//    signal (e.g. "authController.js" nudges login/register code apart
//    from unrelated files with similar-looking logic).
//
//    Using /api/embed (not the older /api/embeddings): it accepts an
//    array of texts and returns all their vectors in ONE request, instead
//    of one HTTP round-trip per chunk. This matters more than client-side
//    concurrency (Promise.all) when Ollama itself processes requests
//    mostly serially on a CPU-only machine — batching at the API level
//    is what actually reduces wall-clock time.
// ─────────────────────────────────────────────────────────────────────────
const OLLAMA_EMBED_URL = 'http://localhost:11434/api/embed';

async function getEmbedding(text) {
  const [embedding] = await getEmbeddingsBatch([text]);
  return embedding;
}

async function getEmbeddingsBatch(texts) {
  const response = await fetch(OLLAMA_EMBED_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: EMBED_MODEL, input: texts }),
  });
  if (!response.ok) {
    throw new Error(`Ollama embedding request failed: ${response.status}`);
  }
  const data = await response.json();
  return data.embeddings; // array of vectors, same order as input texts
}

// ─────────────────────────────────────────────────────────────────────────
// 3. Cosine similarity — how "aligned" two vectors are (1 = identical
//    direction/meaning, 0 = unrelated, -1 = opposite).
// ─────────────────────────────────────────────────────────────────────────
function cosineSimilarity(a, b) {
  let dot = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

// ─────────────────────────────────────────────────────────────────────────
// 4. Ingestion — chunk + embed + store, scoped to one user's session.
//    Called once per ZIP upload. Old chunks from a previous upload are
//    cleared first, same "replace on new upload" behavior as ProjectSession.
// ─────────────────────────────────────────────────────────────────────────
async function ingestProjectChunks(userId, files) {
  const sessionId = String(userId); // userId is an Int in this project; sessionId column is String
  const crypto = require('crypto');

  // 1. Figure out which files actually changed since last time, so we
  //    only re-chunk/re-embed those. Unchanged files keep their existing
  //    chunks untouched — this is what makes re-uploads with small edits
  //    fast instead of re-embedding all 60 files every time.
  const existingHashes = await prisma.ingestedFileHash.findMany({ where: { sessionId } });
  const hashByPath = Object.fromEntries(existingHashes.map((h) => [h.filePath, h.contentHash]));

  const currentPaths = new Set(files.map((f) => f.path));
  const changedFiles = [];
  const unchangedCount = { value: 0 };

  for (const file of files) {
    const hash = crypto.createHash('sha256').update(file.content).digest('hex');
    if (hashByPath[file.path] === hash) {
      unchangedCount.value++;
    } else {
      changedFiles.push({ ...file, _hash: hash });
    }
  }

  // Files that existed before but aren't in this upload anymore (deleted
  // from the project) — their old chunks + hash records should go too.
  const removedPaths = existingHashes
    .map((h) => h.filePath)
    .filter((p) => !currentPaths.has(p));

  console.log(
    `Incremental ingestion: ${changedFiles.length} changed, ${unchangedCount.value} unchanged (skipped), ${removedPaths.length} removed`
  );

  // 2. Clean up chunks/hashes for changed + removed files only — NOT a
  //    blanket deleteMany for the whole session anymore, since that would
  //    also wipe the unchanged files' chunks we're trying to preserve.
  const pathsToClear = [...changedFiles.map((f) => f.path), ...removedPaths];
  if (pathsToClear.length > 0) {
    await prisma.codeChunk.deleteMany({ where: { sessionId, filePath: { in: pathsToClear } } });
    await prisma.ingestedFileHash.deleteMany({ where: { sessionId, filePath: { in: pathsToClear } } });
  }

  // 3. Chunk only the changed files.
  const rawChunks = chunkAllFiles(changedFiles);

  // Dedupe exact-duplicate content BEFORE embedding. This project's tmp/
  // folder had ~10 near-identical "assignment-api-docs.md" files — embedding
  // each one separately wastes compute AND causes retrieval to return 10
  // copies of the same answer, crowding out other genuinely different files.
  // We keep one representative chunk per unique content and note which
  // other files shared that exact content, so nothing is silently lost.
  const seenContentHashes = new Map(); // contentHash -> representative chunk
  for (const chunk of rawChunks) {
    const contentHash = crypto.createHash('sha256').update(chunk.content.trim()).digest('hex');
    const existing = seenContentHashes.get(contentHash);
    if (existing) {
      existing.duplicateOf = existing.duplicateOf || [];
      existing.duplicateOf.push(chunk.filePath);
    } else {
      seenContentHashes.set(contentHash, chunk);
    }
  }
  const chunks = [...seenContentHashes.values()];
  const duplicatesSkipped = rawChunks.length - chunks.length;
  if (duplicatesSkipped > 0) {
    console.log(`Skipped embedding ${duplicatesSkipped} exact-duplicate chunk(s) (identical content already indexed elsewhere)`);
  }

  const BATCH_SIZE = 15;
  for (let i = 0; i < chunks.length; i += BATCH_SIZE) {
    const batch = chunks.slice(i, i + BATCH_SIZE);
    const texts = batch.map((chunk) => `File: ${chunk.filePath}\n${chunk.content}`);
    const embeddings = await getEmbeddingsBatch(texts);

    await prisma.codeChunk.createMany({
      data: batch.map((chunk, idx) => ({
        sessionId,
        filePath: chunk.filePath, // kept clean/original — cleanup-by-filePath logic above depends on exact matches
        content: chunk.content,
        embedding: embeddings[idx],
      })),
    });
  }

  // 4. Record the new hashes for changed files, so the NEXT upload can
  //    compare against them.
  if (changedFiles.length > 0) {
    await prisma.ingestedFileHash.createMany({
      data: changedFiles.map((f) => ({ sessionId, filePath: f.path, contentHash: f._hash })),
      skipDuplicates: true,
    });
  }

  const totalChunkCount = await prisma.codeChunk.count({ where: { sessionId } });
  return { chunkCount: totalChunkCount, changedFileCount: changedFiles.length, skippedFileCount: unchangedCount.value };
}

// ─────────────────────────────────────────────────────────────────────────
// 5. Retrieval — embed the question, rank stored chunks by similarity,
//    return the top K. This is what makes it "retrieval-augmented":
//    the LLM only sees what's relevant to THIS question, not everything.
//
//    Hybrid boost: pure vector similarity can miss chunks where the exact
//    word the user typed (e.g. "stripe") appears in the code/path, but the
//    surrounding vocabulary is different enough that the embedding doesn't
//    rank it highly. A small literal-keyword boost catches these cases
//    without abandoning semantic search for everything else.
// ─────────────────────────────────────────────────────────────────────────
const STOPWORDS = new Set(['how', 'does', 'the', 'is', 'are', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'work', 'works', 'app', 'this']);
const KEYWORD_BOOST = 0.15;

function extractKeywords(question) {
  return question
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((word) => word.length > 2 && !STOPWORDS.has(word));
}

async function retrieveRelevantChunks(userId, question, topK = 6, options = {}) {
  const { useReranking = true, candidatePoolSize = topK * 3 } = options;

  const sessionId = String(userId); // same conversion as ingestProjectChunks
  const queryEmbedding = await getEmbedding(question);
  const keywords = extractKeywords(question);

  const allChunks = await prisma.codeChunk.findMany({
    where: { sessionId },
  });

  if (allChunks.length === 0) return [];

  const scored = allChunks.map((chunk) => {
    const semanticScore = cosineSimilarity(queryEmbedding, chunk.embedding);

    const haystack = (chunk.filePath + ' ' + chunk.content).toLowerCase();
    const keywordHits = keywords.filter((kw) => haystack.includes(kw)).length;
    const keywordBoost = keywordHits > 0 ? KEYWORD_BOOST * (keywordHits / keywords.length) : 0;

    return {
      filePath: chunk.filePath,
      content: chunk.content,
      score: semanticScore + keywordBoost,
    };
  });

  scored.sort((a, b) => b.score - a.score);

  // Diversity cap: without this, a file with many small, well-matching
  // chunks (common now that chunking is function-level, not 60-line
  // windows) can fill every slot in topK, crowding out other genuinely
  // relevant files (e.g. the model file when the controller dominates).
  // Take the best-scoring chunks first, but skip any file's 3rd+ chunk.
  // Stage 1 pool is wider and allows slightly more per file than the
  // final result, since re-ranking (stage 2) does the real narrowing.
  const poolTargetSize = useReranking ? candidatePoolSize : topK;
  const MAX_CHUNKS_PER_FILE = useReranking ? 4 : 2;
  const fileCounts = {};
  const diverseResults = [];

  for (const result of scored) {
    const count = fileCounts[result.filePath] || 0;
    if (count >= MAX_CHUNKS_PER_FILE) continue;
    fileCounts[result.filePath] = count + 1;
    diverseResults.push(result);
    if (diverseResults.length >= poolTargetSize) break;
  }

  if (!useReranking) return diverseResults;

  // Stage 2: hand the wider pool to the LLM re-ranker to pick the truly
  // best topK, using actual comprehension rather than vector distance.
  return rerankChunks(question, diverseResults, topK);
}

// ─────────────────────────────────────────────────────────────────────────
// 6. Re-ranking — a second, more careful pass over a wider candidate pool.
//
//    Why: cosine similarity + keyword boost is fast but approximate — it
//    can rank a "kind of related" chunk above a "exactly what's needed"
//    chunk. Re-ranking fixes this by asking an LLM to actually READ each
//    candidate and judge relevance directly, which is slower per-item but
//    far more accurate. So: cast a wide net cheaply (stage 1), then spend
//    the expensive judgment only on that smaller pool (stage 2) — not on
//    every chunk in the project.
// ─────────────────────────────────────────────────────────────────────────
// Parses the re-ranker's response into [{index, score}, ...].
// llama-3.1-8b-instant doesn't reliably stick to "JSON only" instructions —
// in practice it often outputs lines like "[3] - 8" or
// "[10] File: routes/stripeRoutes.js - 10 (explanation...)", sometimes with
// a preamble sentence before the list. Rather than fight the model into
// stricter JSON compliance, we parse whatever shape it gives us:
//   1. Try strict JSON first (covers cases where it DOES comply).
//   2. Fall back to a line-by-line regex that pulls [index] ... - score
//      out of freeform text, which is robust to the variations observed.
function parseRankingResponse(raw, candidateCount) {
  const cleaned = raw.trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/i, '').trim();

  // Attempt 1: strict JSON
  const jsonMatch = cleaned.match(/\[[\s\S]*\]/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      if (Array.isArray(parsed) && parsed.every((r) => typeof r.index === 'number')) {
        return parsed;
      }
    } catch {
      // fall through to line parsing
    }
  }

  // Attempt 2: line-by-line "[index] ... - score" extraction.
  // Score is taken as the number immediately after a "-" that isn't part
  // of a filename (filenames have "-" followed by letters, e.g.
  // "1744736292229-assignment-api-docs.md" — no false match there since
  // the character after those dashes is a letter, not a digit).
  const results = [];
  for (const line of cleaned.split('\n')) {
    const indexMatch = line.match(/^\[(\d+)\]/);
    if (!indexMatch) continue;
    const index = parseInt(indexMatch[1], 10);
    if (index >= candidateCount) continue; // guard against hallucinated indices

    const scoreMatches = [...line.matchAll(/-\s*(\d{1,2})(?!\d)/g)];
    if (scoreMatches.length === 0) continue;
    const score = parseInt(scoreMatches[scoreMatches.length - 1][1], 10);
    if (score >= 0 && score <= 10) {
      results.push({ index, score });
    }
  }

  return results;
}

async function rerankChunks(question, candidates, topK = 6) {
  if (candidates.length <= topK) return candidates; // nothing to narrow down

  const groq = require('./groqClient');

  const listForPrompt = candidates
    .map((c, i) => `[${i}] File: ${c.filePath}\n${c.content.slice(0, 400)}`)
    .join('\n\n---\n\n');

  const prompt = `Question: "${question}"

Below are ${candidates.length} code snippets (indexed [0] to [${candidates.length - 1}]). Rate how directly relevant each one is to answering the question, on a 0-10 scale (10 = directly answers it, 0 = unrelated).

${listForPrompt}

Respond with ONLY a JSON array of {"index": number, "score": number}, sorted by score descending. No other text.`;

  try {
    const completion = await groq.chat.completions.create({
      model: 'llama-3.1-8b-instant', // small/fast model — this is a scoring pass, not generation
      messages: [{ role: 'user', content: prompt }],
      temperature: 0,
      max_tokens: 800,
    });

    const raw = completion.choices[0]?.message?.content || '[]';
    const ranked = parseRankingResponse(raw, candidates.length)
      .sort((a, b) => b.score - a.score); // don't trust the model's own ordering, sort ourselves

    const reordered = ranked
      .filter((r) => candidates[r.index]) // guard against out-of-range indices
      .map((r) => candidates[r.index]);

    return reordered.length > 0 ? reordered.slice(0, topK) : candidates.slice(0, topK);
  } catch (err) {
    // Re-ranking is an enhancement, not a dependency — if Groq is slow,
    // down, or returns malformed JSON, fall back to the stage-1 ordering
    // rather than failing the whole question.
    console.error('Re-ranking failed, falling back to vector+keyword order:', err.message);
    return candidates.slice(0, topK);
  }
}

module.exports = {
  chunkAllFiles,
  getEmbedding,
  getEmbeddingsBatch,
  cosineSimilarity,
  ingestProjectChunks,
  retrieveRelevantChunks,
  rerankChunks,
};