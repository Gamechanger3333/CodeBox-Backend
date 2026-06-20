const { extractProjectFiles, analyzeProject, askAboutProject } = require('../utils/projectAnalyzer');

// In-memory store for project context per user session
// In production, store this in Redis or DB
const projectSessions = new Map();

const SESSION_TTL = 2 * 60 * 60 * 1000; // 2 hours

function getSessionKey(userId) {
  return `project:${userId}`;
}

function cleanupExpiredSessions() {
  const now = Date.now();
  for (const [key, session] of projectSessions.entries()) {
    if (now - session.createdAt > SESSION_TTL) {
      projectSessions.delete(key);
    }
  }
}

// Upload and analyze a project ZIP
exports.uploadProject = async (req, res, next) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No ZIP file uploaded' });
    }

    const userId = req.user.id;
    const zipBuffer = req.file.buffer;
    const originalName = req.file.originalname;

    // Extract files from ZIP
    let extracted;
    try {
      extracted = await extractProjectFiles(zipBuffer);
    } catch (err) {
      return res.status(400).json({ error: 'Failed to parse ZIP file. Make sure it is a valid ZIP archive.' });
    }

    if (extracted.files.length === 0) {
      return res.status(400).json({ error: 'No readable source files found in this ZIP. Make sure it contains source code files.' });
    }

    // Run AI analysis
    const analysis = await analyzeProject(extracted.fileTree, extracted.files);

    // Store project context in session
    cleanupExpiredSessions();
    const sessionKey = getSessionKey(userId);
    projectSessions.set(sessionKey, {
      projectName: originalName.replace(/\.zip$/i, ''),
      fileTree: extracted.fileTree,
      files: extracted.files,
      stats: extracted.stats,
      conversationHistory: [],
      createdAt: Date.now(),
    });

    res.json({
      success: true,
      projectName: originalName.replace(/\.zip$/i, ''),
      stats: extracted.stats,
      fileTree: extracted.fileTree,
      analysis,
    });
  } catch (error) {
    console.error('Project upload error:', error);
    next(error);
  }
};

// Ask a follow-up question about the loaded project
exports.askProject = async (req, res, next) => {
  try {
    const userId = req.user.id;
    const { message } = req.body;

    if (!message?.trim()) {
      return res.status(400).json({ error: 'No message provided' });
    }

    const sessionKey = getSessionKey(userId);
    const session = projectSessions.get(sessionKey);

    if (!session) {
      return res.status(404).json({ error: 'No project loaded. Please upload a project ZIP first.' });
    }

    // Check session not expired
    if (Date.now() - session.createdAt > SESSION_TTL) {
      projectSessions.delete(sessionKey);
      return res.status(410).json({ error: 'Project session expired. Please re-upload your project.' });
    }

    const response = await askAboutProject(
      session.fileTree,
      session.files,
      session.conversationHistory,
      message
    );

    // Append to history (keep last 10 turns to stay within context)
    session.conversationHistory.push({ role: 'user', content: message });
    session.conversationHistory.push({ role: 'assistant', content: response });
    if (session.conversationHistory.length > 20) {
      session.conversationHistory = session.conversationHistory.slice(-20);
    }

    res.json({ response, projectName: session.projectName });
  } catch (error) {
    console.error('Project ask error:', error);
    next(error);
  }
};

// Get current project session info
exports.getProjectSession = async (req, res) => {
  const userId = req.user.id;
  const sessionKey = getSessionKey(userId);
  const session = projectSessions.get(sessionKey);

  if (!session || Date.now() - session.createdAt > SESSION_TTL) {
    return res.json({ hasProject: false });
  }

  res.json({
    hasProject: true,
    projectName: session.projectName,
    stats: session.stats,
    fileTree: session.fileTree,
    messageCount: session.conversationHistory.length / 2,
  });
};

// Clear project session
exports.clearProject = async (req, res) => {
  const userId = req.user.id;
  projectSessions.delete(getSessionKey(userId));
  res.json({ success: true });
};