const { extractProjectFiles, analyzeProject, askAboutProjectRAG } = require('../utils/projectAnalyzer');
const { ingestProjectChunks, retrieveRelevantChunks } = require('../utils/ragEngine');
const prisma = require('../models/prismaClient');

const MAX_HISTORY = 20; // keep last 10 turns (20 messages)
const MAX_MESSAGE_LENGTH = 8000; // same reasoning as conversationController — cap LLM cost per request

// ─────────────────────────────────────────────────────────────────────────────
// Upload and analyze a project ZIP
// ─────────────────────────────────────────────────────────────────────────────
exports.uploadProject = async (req, res, next) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No ZIP file uploaded' });
    }

    const userId  = req.user.id;
    const zipBuffer   = req.file.buffer;
    const originalName = req.file.originalname;
    const projectName  = originalName.replace(/\.zip$/i, '');

    // 1. Extract files from ZIP
    let extracted;
    try {
      extracted = await extractProjectFiles(zipBuffer);
    } catch {
      return res.status(400).json({ error: 'Failed to parse ZIP file. Make sure it is a valid ZIP archive.' });
    }

    if (extracted.files.length === 0) {
      return res.status(400).json({ error: 'No readable source files found in this ZIP. Make sure it contains source code files.' });
    }

    // 2. Run AI analysis (still uses the full capped context — this is the
    //    one-time overview, not per-question, so the existing approach is fine)
    const analysis = await analyzeProject(extracted.fileTree, extracted.files);

    // 3. Persist to DB (upsert — one row per user, new upload replaces old)
    //    ragStatus starts "pending" — background ingestion below updates it.
    await prisma.projectSession.upsert({
      where:  { userId },
      update: {
        projectName,
        fileTree: extracted.fileTree,
        files:    JSON.stringify(extracted.files),
        stats:    JSON.stringify(extracted.stats),
        analysis,
        history:  '[]',          // reset chat history on new upload
        ragStatus: 'pending',
        ragChunkCount: 0,
      },
      create: {
        userId,
        projectName,
        fileTree: extracted.fileTree,
        files:    JSON.stringify(extracted.files),
        stats:    JSON.stringify(extracted.stats),
        analysis,
        history:  '[]',
        ragStatus: 'pending',
        ragChunkCount: 0,
      },
    });

    res.json({
      success: true,
      projectName,
      stats:    extracted.stats,
      fileTree: extracted.fileTree,
      analysis,
      ragStatus: 'pending',
    });

    // 4. Chunk + embed + store for RAG — runs AFTER the response is already
    //    sent. On CPU-only hardware, embedding 60+ files takes minutes; the
    //    user shouldn't stare at a spinner for that when their analysis is
    //    already ready. ragStatus lets the frontend (and askProject) know
    //    when indexing has actually finished, instead of guessing from timing.
    ingestProjectChunks(userId, extracted.allFiles)
      .then(async ({ chunkCount, changedFileCount, skippedFileCount }) => {
        console.log(
          `RAG ingestion complete for user ${userId}: ${chunkCount} total chunks ` +
          `(${changedFileCount} files re-embedded, ${skippedFileCount} unchanged & skipped)`
        );
        await prisma.projectSession.update({
          where: { userId },
          data: { ragStatus: 'ready', ragChunkCount: chunkCount },
        }).catch(() => {}); // session may have been cleared/replaced mid-ingestion — safe to ignore
      })
      .catch(async (err) => {
        console.error('RAG ingestion failed (follow-up Q&A will be degraded):', err);
        await prisma.projectSession.update({
          where: { userId },
          data: { ragStatus: 'failed' },
        }).catch(() => {});
      });
  } catch (error) {
    console.error('Project upload error:', error);
    next(error);
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Ask a follow-up question about the loaded project
// ─────────────────────────────────────────────────────────────────────────────
exports.askProject = async (req, res, next) => {
  try {
    const userId = req.user.id;
    const { message } = req.body;

    if (!message?.trim()) {
      return res.status(400).json({ error: 'No message provided' });
    }

    if (message.length > MAX_MESSAGE_LENGTH) {
      return res.status(400).json({ error: `Message too long (max ${MAX_MESSAGE_LENGTH} characters)` });
    }

    // Load session from DB
    const session = await prisma.projectSession.findUnique({ where: { userId } });

    if (!session) {
      return res.status(404).json({ error: 'No project loaded. Please upload a project ZIP first.' });
    }

    if (session.ragStatus === 'pending') {
      return res.status(423).json({
        error: 'Your project is still being indexed for Q&A (this runs in the background and can take a couple of minutes on this machine). Please try again shortly.',
        ragStatus: 'pending',
      });
    }

    if (session.ragStatus === 'failed') {
      return res.status(500).json({
        error: 'Indexing this project for Q&A failed. Try re-uploading — if it keeps failing, check that the embedding service (Ollama) is running.',
        ragStatus: 'failed',
      });
    }

    const history = JSON.parse(session.history);

    // Retrieve only the chunks relevant to this specific question, instead
    // of sending the entire (possibly truncated) project on every message.
    const relevantChunks = await retrieveRelevantChunks(userId, message);

    if (relevantChunks.length === 0) {
      return res.status(404).json({
        error: 'No relevant content found for that question in the indexed project.',
      });
    }

    // Get AI response
    const response = await askAboutProjectRAG(
      relevantChunks,
      history,
      message
    );

    // Update history (keep last MAX_HISTORY messages)
    const updatedHistory = [
      ...history,
      { role: 'user',      content: message  },
      { role: 'assistant', content: response },
    ].slice(-MAX_HISTORY);

    // Save updated history back to DB
    await prisma.projectSession.update({
      where: { userId },
      data:  { history: JSON.stringify(updatedHistory) },
    });

    res.json({ response, projectName: session.projectName });
  } catch (error) {
    console.error('Project ask error:', error);
    next(error);
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Get current project session info (called on page load)
// Returns the saved analysis too so the frontend can restore the chat view
// ─────────────────────────────────────────────────────────────────────────────
exports.getProjectSession = async (req, res) => {
  try {
    const userId  = req.user.id;
    const session = await prisma.projectSession.findUnique({ where: { userId } });

    if (!session) {
      return res.json({ hasProject: false });
    }

    const history = JSON.parse(session.history);

    res.json({
      hasProject:   true,
      projectName:  session.projectName,
      stats:        JSON.parse(session.stats),
      fileTree:     session.fileTree,
      analysis:     session.analysis,          // ← restored so UI can show it
      history,                                 // ← restored chat history
      messageCount: history.length / 2,
      ragStatus:      session.ragStatus,       // "pending" | "ready" | "failed"
      ragChunkCount:  session.ragChunkCount,
    });
  } catch (error) {
    console.error('Get project session error:', error);
    res.json({ hasProject: false });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Clear project session
// ─────────────────────────────────────────────────────────────────────────────
exports.clearProject = async (req, res) => {
  try {
    const userId = req.user.id;
    await prisma.projectSession.deleteMany({ where: { userId } });
    await prisma.codeChunk.deleteMany({ where: { sessionId: String(userId) } });
    await prisma.ingestedFileHash.deleteMany({ where: { sessionId: String(userId) } });
    res.json({ success: true });
  } catch (error) {
    console.error('Clear project error:', error);
    res.json({ success: true }); // still return success — worst case it's already gone
  }
};