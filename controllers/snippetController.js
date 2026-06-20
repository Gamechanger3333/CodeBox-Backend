const { validationResult } = require('express-validator');
const prisma = require('../models/prismaClient');
const { detectLanguage } = require('../utils/codeboxAI');

const validate = (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    res.status(400).json({ error: errors.array()[0].msg });
    return false;
  }
  return true;
};

exports.createSnippet = async (req, res) => {
  if (!validate(req, res)) return;

  const userId = req.user.id;
  const { title, code, language, description, isPublic } = req.body;

  try {
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

exports.getSnippet = async (req, res) => {
  if (!validate(req, res)) return;

  const { snippetId } = req.params;
  const userId = req.user.id;

  try {
    const snippet = await prisma.snippet.findFirst({ where: { id: snippetId, userId } });
    if (!snippet) return res.status(404).json({ error: 'Snippet not found' });
    res.json({ snippet });
  } catch (error) {
    res.status(500).json({ error: 'Server error' });
  }
};

exports.deleteSnippet = async (req, res) => {
  if (!validate(req, res)) return;

  const { snippetId } = req.params;
  const userId = req.user.id;

  try {
    const snippet = await prisma.snippet.findFirst({ where: { id: snippetId, userId } });
    if (!snippet) return res.status(404).json({ error: 'Snippet not found' });
    await prisma.snippet.delete({ where: { id: snippetId } });
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete snippet' });
  }
};

/**
 * Fix #10: the update where-clause now includes userId.
 * Previously the ownership check was a separate findFirst, but the update
 * itself only filtered by id — a race condition or logic error could have
 * updated the wrong record. Both the check AND the update now require userId.
 */
exports.updateSnippet = async (req, res) => {
  if (!validate(req, res)) return;

  const { snippetId } = req.params;
  const userId = req.user.id;
  const { title, code, language, description, isPublic } = req.body;

  try {
    // Verify ownership first.
    const snippet = await prisma.snippet.findFirst({ where: { id: snippetId, userId } });
    if (!snippet) return res.status(404).json({ error: 'Snippet not found' });

    // Update also scoped to userId — belt-and-suspenders ownership enforcement.
    const updated = await prisma.snippet.update({
      where: { id: snippetId, userId },
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