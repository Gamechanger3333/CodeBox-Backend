const express = require('express');
const router = express.Router();
const conversationController = require('../controllers/conversationController');
const snippetController = require('../controllers/snippetController');
const authenticateToken = require('../middlewares/auth');

// Auth check
router.get('/check_authentication', authenticateToken, conversationController.checkAuthentication);

// Conversations
router.get('/latest_conversation', authenticateToken, conversationController.latestConversation);
router.post('/start_conversation', authenticateToken, conversationController.startConversation);
router.post('/send_message', authenticateToken, conversationController.sendMessage);
router.get('/get_conversation/:conversationId', authenticateToken, conversationController.getConversation);
router.get('/getAllConversationIDs', authenticateToken, conversationController.getAllConversationIds);
router.delete('/conversation/:conversationId', authenticateToken, conversationController.deleteConversation);
router.patch('/conversation/:conversationId/pin', authenticateToken, conversationController.togglePin);
router.patch('/conversation/:conversationId/title', authenticateToken, conversationController.updateTitle);

// Code analysis
router.post('/analyze_code', authenticateToken, conversationController.analyzeCode);

// Snippets
router.get('/snippets', authenticateToken, snippetController.getSnippets);
router.post('/snippets', authenticateToken, snippetController.createSnippet);
router.get('/snippets/:snippetId', authenticateToken, snippetController.getSnippet);
router.put('/snippets/:snippetId', authenticateToken, snippetController.updateSnippet);
router.delete('/snippets/:snippetId', authenticateToken, snippetController.deleteSnippet);

module.exports = router;
