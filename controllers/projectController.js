const { extractProjectFiles, analyzeProject, askAboutProject } = require('../utils/projectAnalyzer');
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

    // 2. Run AI analysis
    const analysis = await analyzeProject(extracted.fileTree, extracted.files);

    // 3. Persist to DB (upsert — one row per user, new upload replaces old)
    await prisma.projectSession.upsert({
      where:  { userId },
      update: {
        projectName,
        fileTree: extracted.fileTree,
        files:    JSON.stringify(extracted.files),
        stats:    JSON.stringify(extracted.stats),
        analysis,
        history:  '[]',          // reset chat history on new upload
      },
      create: {
        userId,
        projectName,
        fileTree: extracted.fileTree,
        files:    JSON.stringify(extracted.files),
        stats:    JSON.stringify(extracted.stats),
        analysis,
        history:  '[]',
      },
    });

    res.json({
      success: true,
      projectName,
      stats:    extracted.stats,
      fileTree: extracted.fileTree,
      analysis,
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

    const files   = JSON.parse(session.files);
    const history = JSON.parse(session.history);

    // Get AI response
    const response = await askAboutProject(
      session.fileTree,
      files,
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
    res.json({ success: true });
  } catch (error) {
    console.error('Clear project error:', error);
    res.json({ success: true }); // still return success — worst case it's already gone
  }
};