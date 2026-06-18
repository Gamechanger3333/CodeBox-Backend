const express = require('express');
const authController = require('../controllers/authController');

const router = express.Router();

// Standard auth
router.post('/signup', authController.signup);
router.post('/login', authController.login);
router.get('/logout', authController.logout);

// Password reset flow (3 steps)
router.post('/forgot-password', authController.forgotPassword);   // Step 1: Send OTP
router.post('/verify-otp', authController.verifyOtp);             // Step 2: Verify OTP
router.post('/reset-password', authController.resetPassword);     // Step 3: Set new password

module.exports = router;
