const express = require('express');
const router = express.Router();
const multer = require('multer');
const conversationController = require('../controllers/conversationController');
const snippetController = require('../controllers/snippetController');
const projectController = require('../controllers/projectController');
const authenticateToken = require('../middlewares/auth');

// Multer: memory storage for ZIP uploads (max 50MB)
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 50 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    if (file.mimetype === 'application/zip' ||
        file.mimetype === 'application/x-zip-compressed' ||
        file.originalname.endsWith('.zip')) {
      cb(null, true);
    } else {
      cb(new Error('Only ZIP files are accepted'));
    }
  },
});

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

// Project analysis
router.post('/project/upload', authenticateToken, upload.single('project'), projectController.uploadProject);
router.post('/project/ask', authenticateToken, projectController.askProject);
router.get('/project/session', authenticateToken, projectController.getProjectSession);
router.delete('/project/session', authenticateToken, projectController.clearProject);

module.exports = router;