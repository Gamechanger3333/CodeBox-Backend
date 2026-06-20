const { sendMessage, startConversation, getConversation, deleteConversationById } = require('../services/conversationService');
const { analyzeCode } = require('../utils/codeboxAI');
const prisma = require('../models/prismaClient');

// Caps how much text a single request can push into the LLM. The body-parser
// limit (10mb) is far too generous for this — without a per-field cap a
// single user can run up a large Groq bill by sending huge payloads
// repeatedly within the rate limit window.
const MAX_MESSAGE_LENGTH = 8000;

// Start a new conversation
exports.startConversation = async (req, res, next) => {
  const userId = req.user.id;
  try {
    const conversation = await startConversation(userId);
    res.json({ conversationId: conversation.id });
  } catch (error) {
    next(error);
  }
};

// Send a message
exports.sendMessage = async (req, res, next) => {
  const { conversationId, message } = req.body;
  const userId = req.user.id;

  try {
    if (!conversationId || !message) {
      return res.status(400).json({ error: 'Missing conversationId or message' });
    }

    if (message.length > MAX_MESSAGE_LENGTH) {
      return res.status(400).json({ error: `Message too long (max ${MAX_MESSAGE_LENGTH} characters)` });
    }

    const conversation = await prisma.conversation.findUnique({
      where: { id: conversationId, userId },
    });

    if (!conversation) {
      return res.status(404).json({ error: 'Conversation not found' });
    }

    // 'sender' is always 'user' for messages coming through this endpoint —
    // never trust the client to tell us who sent the message, or anyone
    // could post fake "bot" messages into their own history.
    const botResponse = await sendMessage(conversationId, message, 'user');
    
    // Fetch updated conversation title
    const updatedConv = await prisma.conversation.findUnique({
      where: { id: conversationId },
      select: { title: true },
    });

    res.json({ response: botResponse, title: updatedConv?.title });
  } catch (error) {
    next(error);
  }
};

// Get all messages in a conversation
exports.getConversation = async (req, res, next) => {
  const { conversationId } = req.params;
  const userId = req.user.id;

  try {
    const conversation = await prisma.conversation.findUnique({
      where: { id: conversationId, userId },
      include: { messages: { orderBy: { createdAt: 'asc' } } },
    });

    if (!conversation) {
      return res.status(404).json({ error: 'Conversation not found' });
    }

    res.json({ conversation });
  } catch (error) {
    next(error);
  }
};

// Delete a conversation
exports.deleteConversation = async (req, res) => {
  const { conversationId } = req.params;
  const userId = req.user.id;

  try {
    const conversation = await prisma.conversation.findUnique({
      where: { id: conversationId, userId },
    });

    if (!conversation) {
      return res.status(404).json({ error: 'Conversation not found' });
    }

    await deleteConversationById(conversationId);
    return res.status(200).json({ success: true, message: 'Conversation deleted' });
  } catch (error) {
    return res.status(500).json({ success: false, message: 'Server error' });
  }
};

// Get all conversations (with titles) for a user
exports.getAllConversationIds = async (req, res, next) => {
  const userId = req.user.id;

  try {
    const conversations = await prisma.conversation.findMany({
      where: { userId },
      select: { id: true, title: true, createdAt: true, isPinned: true },
      orderBy: [
        { isPinned: 'desc' },
        { createdAt: 'desc' },
      ],
    });
    res.json(conversations);
  } catch (error) {
    next(error);
  }
};

// Get latest conversation
exports.latestConversation = async (req, res) => {
  const userId = req.user.id;

  try {
    const latestConversation = await prisma.conversation.findFirst({
      where: { userId },
      orderBy: { createdAt: 'desc' },
    });

    if (latestConversation) {
      res.json({ conversationId: latestConversation.id });
    } else {
      res.status(404).json({ error: 'No conversations found' });
    }
  } catch (error) {
    res.status(500).json({ error: 'Internal server error' });
  }
};

// Check auth
exports.checkAuthentication = (req, res) => {
  res.json({ authenticated: true, user: req.user });
};

// Pin/unpin a conversation
exports.togglePin = async (req, res) => {
  const { conversationId } = req.params;
  const userId = req.user.id;

  try {
    const conversation = await prisma.conversation.findUnique({
      where: { id: conversationId, userId },
    });

    if (!conversation) {
      return res.status(404).json({ error: 'Conversation not found' });
    }

    const updated = await prisma.conversation.update({
      where: { id: conversationId },
      data: { isPinned: !conversation.isPinned },
    });

    res.json({ isPinned: updated.isPinned });
  } catch (error) {
    res.status(500).json({ error: 'Server error' });
  }
};

// Update conversation title
exports.updateTitle = async (req, res) => {
  const { conversationId } = req.params;
  const { title } = req.body;
  const userId = req.user.id;

  try {
    const conversation = await prisma.conversation.findUnique({
      where: { id: conversationId, userId },
    });

    if (!conversation) {
      return res.status(404).json({ error: 'Conversation not found' });
    }

    const updated = await prisma.conversation.update({
      where: { id: conversationId },
      data: { title: title.trim() },
    });

    res.json({ title: updated.title });
  } catch (error) {
    res.status(500).json({ error: 'Server error' });
  }
};

// Analyze uploaded code
exports.analyzeCode = async (req, res, next) => {
  const { code, filename } = req.body;

  try {
    if (!code) return res.status(400).json({ error: 'No code provided' });
    if (code.length > MAX_MESSAGE_LENGTH) {
      return res.status(400).json({ error: `Code too long to analyze (max ${MAX_MESSAGE_LENGTH} characters)` });
    }
    const analysis = await analyzeCode(code, filename || 'code.txt');
    res.json({ analysis });
  } catch (error) {
    next(error);
  }
};
