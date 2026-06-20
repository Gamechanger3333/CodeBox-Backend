const prisma = require('../models/prismaClient');
const { getCodeBoxAIResponse, generateConversationTitle } = require('../utils/codeboxAI');

// Maximum number of messages to send to the AI for context.
// Keeps Groq token costs predictable and prevents slow queries on long chats.
const MAX_CONTEXT_MESSAGES = 30;

exports.startConversation = async (userId) => {
  return prisma.conversation.create({ data: { userId } });
};

/**
 * Send a message and get an AI response.
 * Caps the history at MAX_CONTEXT_MESSAGES before calling Groq.
 */
exports.sendMessage = async (conversationId, message, sender) => {
  if (!conversationId || !message || !sender) {
    throw new Error('Missing conversationId, message, or sender');
  }

  // Fetch the last MAX_CONTEXT_MESSAGES messages for context — not the whole history.
  // This prevents unbounded DB reads and runaway Groq token costs on long conversations.
  const existingMessages = await prisma.message.findMany({
    where: { conversationId },
    orderBy: { createdAt: 'asc' },
    take: MAX_CONTEXT_MESSAGES,
  });

  const isFirstMessage = existingMessages.length === 0;

  const fullHistory = [
    ...existingMessages.map(m => ({ sender: m.sender, content: m.content })),
    { sender: 'user', content: message },
  ];

  const botResponse = await getCodeBoxAIResponse(fullHistory);

  // Save user message and bot response in a transaction so we never get
  // a user message without its bot reply (or vice versa) on partial failure.
  await prisma.$transaction([
    prisma.message.create({ data: { conversationId, sender, content: message } }),
    prisma.message.create({ data: { conversationId, sender: 'bot', content: botResponse } }),
  ]);

  // Auto-generate title on the first message — non-critical, so errors don't bubble.
  if (isFirstMessage) {
    try {
      const title = await generateConversationTitle(message);
      await prisma.conversation.update({ where: { id: conversationId }, data: { title } });
    } catch (e) {
      console.error('Title generation failed:', e.message);
    }
  }

  return botResponse;
};

exports.getConversation = async (conversationId) => {
  return prisma.message.findMany({
    where: { conversationId },
    orderBy: { createdAt: 'asc' },
  });
};

/**
 * Delete a conversation and all its messages atomically.
 * Fix #5: using a Prisma transaction so a crash between the two deletes
 * cannot leave orphaned messages with no parent conversation.
 */
exports.deleteConversationById = async (conversationId) => {
  await prisma.$transaction([
    prisma.message.deleteMany({ where: { conversationId } }),
    prisma.conversation.delete({ where: { id: conversationId } }),
  ]);
  return { success: true };
};