const prisma = require('../models/prismaClient');
const { getCodeBoxAIResponse, generateConversationTitle } = require('../utils/codeboxAI');

// Start a new conversation
exports.startConversation = async (userId) => {
  const conversation = await prisma.conversation.create({
    data: { userId },
  });
  return conversation;
};

// Get all conversation IDs (legacy)
exports.getAllConversationIds = async () => {
  const ids = await prisma.conversationIdOnly.findMany();
  return ids.map((c) => c.id);
};

// Send a message — uses full conversation history for context
exports.sendMessage = async (conversationId, message, sender) => {
  if (!conversationId || !message || !sender) {
    throw new Error('Missing conversationId, message, or sender');
  }

  // Fetch existing messages for context
  const existingMessages = await prisma.message.findMany({
    where: { conversationId },
    orderBy: { createdAt: 'asc' },
  });

  // Build full history including the new message
  const fullHistory = [
    ...existingMessages.map(m => ({ sender: m.sender, content: m.content })),
    { sender: 'user', content: message },
  ];

  // Get AI response with full context
  const botResponse = await getCodeBoxAIResponse(fullHistory);

  // Save user message
  await prisma.message.create({
    data: { conversationId, sender, content: message },
  });

  // Save bot response
  await prisma.message.create({
    data: { conversationId, sender: 'bot', content: botResponse },
  });

  // Auto-generate title if this is the first message
  if (existingMessages.length === 0) {
    try {
      const title = await generateConversationTitle(message);
      await prisma.conversation.update({
        where: { id: conversationId },
        data: { title },
      });
    } catch (e) {
      // Title generation is non-critical
      console.error('Title generation failed:', e.message);
    }
  }

  return botResponse;
};

// Get all messages in a conversation
exports.getConversation = async (conversationId) => {
  return prisma.message.findMany({
    where: { conversationId },
    orderBy: { createdAt: 'asc' },
  });
};

// Delete conversation and all its messages
exports.deleteConversationById = async (conversationId) => {
  await prisma.message.deleteMany({ where: { conversationId } });
  await prisma.conversation.delete({ where: { id: conversationId } });
  return { success: true };
};
