const prisma = require('../models/prismaClient');
const { detectLanguage } = require('../utils/codeboxAI');

// Save a new snippet
exports.createSnippet = async (req, res) => {
  const userId = req.user.id;
  const { title, code, language, description, isPublic } = req.body;

  try {
    if (!title || !code) {
      return res.status(400).json({ error: 'Title and code are required' });
    }

    // Auto-detect language if not provided
    let detectedLanguage = language;
    if (!detectedLanguage || detectedLanguage === 'auto') {
      try {
        detectedLanguage = await detectLanguage(code);
      } catch {
        detectedLanguage = 'plaintext';
      }
    }

    const snippet = await prisma.snippet.create({
      data: {
        title: title.trim(),
        code,
        language: detectedLanguage,
        description: description?.trim() || null,
        isPublic: isPublic || false,
        userId,
      },
    });

    res.status(201).json({ snippet });
  } catch (error) {
    res.status(500).json({ error: 'Failed to create snippet' });
  }
};

// Get all snippets for user
exports.getSnippets = async (req, res) => {
  const userId = req.user.id;

  try {
    const snippets = await prisma.snippet.findMany({
      where: { userId },
      orderBy: { createdAt: 'desc' },
    });
    res.json({ snippets });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch snippets' });
  }
};

// Get single snippet
exports.getSnippet = async (req, res) => {
  const { snippetId } = req.params;
  const userId = req.user.id;

  try {
    const snippet = await prisma.snippet.findFirst({
      where: { id: snippetId, userId },
    });

    if (!snippet) return res.status(404).json({ error: 'Snippet not found' });
    res.json({ snippet });
  } catch (error) {
    res.status(500).json({ error: 'Server error' });
  }
};

// Delete snippet
exports.deleteSnippet = async (req, res) => {
  const { snippetId } = req.params;
  const userId = req.user.id;

  try {
    const snippet = await prisma.snippet.findFirst({
      where: { id: snippetId, userId },
    });

    if (!snippet) return res.status(404).json({ error: 'Snippet not found' });

    await prisma.snippet.delete({ where: { id: snippetId } });
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete snippet' });
  }
};

// Update snippet
exports.updateSnippet = async (req, res) => {
  const { snippetId } = req.params;
  const userId = req.user.id;
  const { title, code, language, description, isPublic } = req.body;

  try {
    const snippet = await prisma.snippet.findFirst({
      where: { id: snippetId, userId },
    });

    if (!snippet) return res.status(404).json({ error: 'Snippet not found' });

    const updated = await prisma.snippet.update({
      where: { id: snippetId },
      data: {
        title: title?.trim() || snippet.title,
        code: code || snippet.code,
        language: language || snippet.language,
        description: description?.trim() ?? snippet.description,
        isPublic: isPublic !== undefined ? isPublic : snippet.isPublic,
      },
    });

    res.json({ snippet: updated });
  } catch (error) {
    res.status(500).json({ error: 'Failed to update snippet' });
  }
};
