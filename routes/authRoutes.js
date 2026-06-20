const express = require('express');
const { body } = require('express-validator');
const authController = require('../controllers/authController');

const router = express.Router();

// ── Reusable validation chains ─────────────────────────────────────────────

const emailRules = body('email')
  .isEmail().withMessage('A valid email address is required')
  .normalizeEmail()
  .isLength({ max: 254 }).withMessage('Email too long');

const passwordRules = body('password')
  .isLength({ min: 8, max: 128 }).withMessage('Password must be 8–128 characters');

const nameRules = body('name')
  .trim()
  .isLength({ min: 1, max: 100 }).withMessage('Name must be 1–100 characters')
  .escape();

const otpRules = body('otp')
  .trim()
  .matches(/^\d{6}$/).withMessage('OTP must be exactly 6 digits');

// ── Routes ─────────────────────────────────────────────────────────────────

router.post('/signup',
  [nameRules, emailRules, passwordRules],
  authController.signup
);

router.post('/login',
  [emailRules, body('password').notEmpty()],
  authController.login
);

// Fix #9: logout must be POST to prevent CSRF via <img src="..."> or link prefetch.
// A GET logout endpoint can be triggered by any page the user visits.
router.post('/logout', authController.logout);

router.post('/forgot-password',
  [emailRules],
  authController.forgotPassword
);

router.post('/verify-otp',
  [emailRules, otpRules],
  authController.verifyOtp
);

router.post('/reset-password',
  [
    body('resetToken').notEmpty().withMessage('Reset token is required'),
    passwordRules,
    body('passwordConfirm').notEmpty().withMessage('Password confirmation is required'),
  ],
  authController.resetPassword
);

module.exports = router;