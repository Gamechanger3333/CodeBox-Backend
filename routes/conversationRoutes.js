const express = require('express');
const { body, param, query } = require('express-validator');
const multer = require('multer');
const conversationController = require('../controllers/conversationController');
const snippetController = require('../controllers/snippetController');
const projectController = require('../controllers/projectController');
const authenticateToken = require('../middlewares/auth');

const router = express.Router();

// Multer: memory storage for ZIP uploads (max 50MB, ZIP only)
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 50 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    if (
      file.mimetype === 'application/zip' ||
      file.mimetype === 'application/x-zip-compressed' ||
      file.originalname.endsWith('.zip')
    ) {
      cb(null, true);
    } else {
      cb(new Error('Only ZIP files are accepted'));
    }
  },
});

// ── Reusable validators ────────────────────────────────────────────────────

const uuidParam = (name) =>
  param(name).isUUID().withMessage(`${name} must be a valid UUID`);

const titleBody = body('title')
  .trim()
  .isLength({ min: 1, max: 100 }).withMessage('Title must be 1–100 characters');

// ── Auth check ─────────────────────────────────────────────────────────────

router.get('/check_authentication', authenticateToken, conversationController.checkAuthentication);

// ── Conversations ──────────────────────────────────────────────────────────

router.get('/latest_conversation', authenticateToken, conversationController.latestConversation);

router.post('/start_conversation', authenticateToken, conversationController.startConversation);

router.post('/send_message',
  authenticateToken,
  [
    body('conversationId').isUUID().withMessage('Invalid conversationId'),
    body('message').trim().isLength({ min: 1, max: 8000 }).withMessage('Message must be 1–8000 characters'),
  ],
  conversationController.sendMessage
);

// Fix #7: pagination support via ?page= and ?limit=
router.get('/getAllConversationIDs',
  authenticateToken,
  [
    query('page').optional().isInt({ min: 1 }).toInt(),
    query('limit').optional().isInt({ min: 1, max: 100 }).toInt(),
  ],
  conversationController.getAllConversationIds
);

router.get('/get_conversation/:conversationId',
  authenticateToken,
  [uuidParam('conversationId')],
  conversationController.getConversation
);

router.delete('/conversation/:conversationId',
  authenticateToken,
  [uuidParam('conversationId')],
  conversationController.deleteConversation
);

router.patch('/conversation/:conversationId/pin',
  authenticateToken,
  [uuidParam('conversationId')],
  conversationController.togglePin
);

router.patch('/conversation/:conversationId/title',
  authenticateToken,
  [uuidParam('conversationId'), titleBody],
  conversationController.updateTitle
);

// ── Code analysis ──────────────────────────────────────────────────────────

router.post('/analyze_code',
  authenticateToken,
  [
    body('code').trim().isLength({ min: 1, max: 8000 }).withMessage('Code must be 1–8000 characters'),
    body('filename').optional().trim().isLength({ max: 255 }).withMessage('Filename too long'),
  ],
  conversationController.analyzeCode
);

// ── Snippets ───────────────────────────────────────────────────────────────

router.get('/snippets', authenticateToken, snippetController.getSnippets);

router.post('/snippets',
  authenticateToken,
  [
    body('title').trim().isLength({ min: 1, max: 100 }).withMessage('Title must be 1–100 characters'),
    body('code').trim().isLength({ min: 1, max: 50000 }).withMessage('Code must be 1–50000 characters'),
    body('language').optional().trim().isLength({ max: 50 }).withMessage('Language name too long'),
    body('description').optional().trim().isLength({ max: 500 }).withMessage('Description max 500 characters'),
  ],
  snippetController.createSnippet
);

router.get('/snippets/:snippetId',
  authenticateToken,
  [uuidParam('snippetId')],
  snippetController.getSnippet
);

router.put('/snippets/:snippetId',
  authenticateToken,
  [
    uuidParam('snippetId'),
    body('title').optional().trim().isLength({ min: 1, max: 100 }),
    body('language').optional().trim().isLength({ max: 50 }),
    body('description').optional().trim().isLength({ max: 500 }),
  ],
  snippetController.updateSnippet
);

router.delete('/snippets/:snippetId',
  authenticateToken,
  [uuidParam('snippetId')],
  snippetController.deleteSnippet
);

// ── Project analysis ───────────────────────────────────────────────────────

router.post('/project/upload', authenticateToken, upload.single('project'), projectController.uploadProject);

router.post('/project/ask',
  authenticateToken,
  [body('message').trim().isLength({ min: 1, max: 8000 }).withMessage('Message must be 1–8000 characters')],
  projectController.askProject
);

router.get('/project/session', authenticateToken, projectController.getProjectSession);

router.delete('/project/session', authenticateToken, projectController.clearProject);

module.exports = router;