const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const { validationResult } = require('express-validator');
const prisma = require('../models/prismaClient');
const { sendPasswordResetOTP, generateOTP } = require('../utils/emailService');

// ── Helpers ────────────────────────────────────────────────────────────────

const signToken = (id) =>
  jwt.sign({ id }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || '7d',
  });

const createSendToken = (user, statusCode, res) => {
  const token = signToken(user.id);
  const cookieExpiresIn = parseInt(process.env.JWT_COOKIE_EXPIRES_IN || '7');

  res.cookie('token', token, {
    expires: new Date(Date.now() + cookieExpiresIn * 24 * 60 * 60 * 1000),
    // httpOnly: JS can never read the cookie — prevents XSS token theft.
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
  });

  const { password, otpCode, otpExpiry, otpAttempts, ...userData } = user;
  res.status(statusCode).json({ status: 'success', token, data: { user: userData } });
};

// Helper: return validation errors as a 400 if express-validator found any.
const validate = (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    res.status(400).json({ status: 'error', message: errors.array()[0].msg });
    return false;
  }
  return true;
};

// ── SIGNUP ─────────────────────────────────────────────────────────────────

exports.signup = async (req, res) => {
  if (!validate(req, res)) return;

  const { name, email, password, passwordConfirm } = req.body;

  try {
    if (password !== passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'Passwords do not match' });
    }

    const existingUser = await prisma.user.findUnique({ where: { email } });
    if (existingUser) {
      return res.status(400).json({ status: 'error', message: 'An account with this email already exists' });
    }

    const hashedPassword = await bcrypt.hash(password, 12);
    const newUser = await prisma.user.create({
      data: { name, email, password: hashedPassword, isVerified: true },
    });

    createSendToken(newUser, 201, res);
  } catch (error) {
    console.error('Signup error:', error);
    res.status(500).json({ status: 'error', message: 'Signup failed. Please try again.' });
  }
};

// ── LOGIN ──────────────────────────────────────────────────────────────────

exports.login = async (req, res, next) => {
  if (!validate(req, res)) return;

  const { email, password } = req.body;

  try {
    const user = await prisma.user.findUnique({ where: { email } });
    if (!user) {
      return res.status(401).json({ status: 'error', message: 'Incorrect email or password' });
    }

    const passwordsMatch = await bcrypt.compare(password, user.password);
    if (!passwordsMatch) {
      return res.status(401).json({ status: 'error', message: 'Incorrect email or password' });
    }

    createSendToken(user, 200, res);
  } catch (error) {
    next(error);
  }
};

// ── LOGOUT ─────────────────────────────────────────────────────────────────
// POST — not GET — to prevent CSRF logout via image/link prefetch.

exports.logout = (req, res) => {
  res.cookie('token', '', {
    expires: new Date(Date.now() + 10 * 1000),
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
  });
  res.status(200).json({ status: 'success', message: 'Logged out successfully' });
};

// ── FORGOT PASSWORD — Step 1: Send OTP ───────────────────────────────────

exports.forgotPassword = async (req, res) => {
  if (!validate(req, res)) return;

  const { email } = req.body;

  try {
    const user = await prisma.user.findUnique({ where: { email } });

    // Always return success to prevent email enumeration.
    if (!user) {
      return res.status(200).json({
        status: 'success',
        message: 'If an account with this email exists, you will receive an OTP shortly.',
      });
    }

    const otp = generateOTP();
    const otpExpiry = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes

    const hashedOtp = await bcrypt.hash(otp, 10);
    await prisma.user.update({
      where: { email },
      data: { otpCode: hashedOtp, otpExpiry, otpAttempts: 0 },
    });

    await sendPasswordResetOTP(email, user.name, otp);
    console.log(`📧 OTP sent to ${email}`);

    res.status(200).json({
      status: 'success',
      message: 'OTP sent to your email address. Check your inbox.',
    });
  } catch (error) {
    console.error('Forgot password error:', error);
    res.status(500).json({ status: 'error', message: 'Failed to send OTP. Please try again.' });
  }
};

// ── VERIFY OTP — Step 2 ────────────────────────────────────────────────────

exports.verifyOtp = async (req, res) => {
  if (!validate(req, res)) return;

  const { email, otp } = req.body;

  try {
    const user = await prisma.user.findUnique({ where: { email } });

    if (!user || !user.otpCode || !user.otpExpiry) {
      return res.status(400).json({ status: 'error', message: 'No active OTP found. Please request a new one.' });
    }

    if (new Date() > user.otpExpiry) {
      await prisma.user.update({
        where: { email },
        data: { otpCode: null, otpExpiry: null, otpAttempts: 0 },
      });
      return res.status(400).json({ status: 'error', message: 'OTP has expired. Please request a new one.' });
    }

    if (user.otpAttempts >= 5) {
      await prisma.user.update({
        where: { email },
        data: { otpCode: null, otpExpiry: null, otpAttempts: 0 },
      });
      return res.status(429).json({ status: 'error', message: 'Too many failed attempts. Please request a new OTP.' });
    }

    const isValid = await bcrypt.compare(otp, user.otpCode);

    if (!isValid) {
      await prisma.user.update({
        where: { email },
        data: { otpAttempts: { increment: 1 } },
      });
      const attemptsLeft = 4 - user.otpAttempts;
      return res.status(400).json({
        status: 'error',
        message: `Incorrect OTP. ${attemptsLeft} attempt${attemptsLeft !== 1 ? 's' : ''} remaining.`,
      });
    }

    // OTP valid — issue a short-lived reset token (15 min, single-purpose).
    const resetToken = jwt.sign(
      { id: user.id, email: user.email, purpose: 'password_reset' },
      process.env.JWT_SECRET,
      { expiresIn: '15m' }
    );

    // Clear OTP — one-time use only.
    await prisma.user.update({
      where: { email },
      data: { otpCode: null, otpExpiry: null, otpAttempts: 0 },
    });

    res.status(200).json({
      status: 'success',
      message: 'OTP verified successfully.',
      resetToken,
    });
  } catch (error) {
    console.error('Verify OTP error:', error);
    res.status(500).json({ status: 'error', message: 'Verification failed. Please try again.' });
  }
};

// ── RESET PASSWORD — Step 3 ────────────────────────────────────────────────

exports.resetPassword = async (req, res) => {
  if (!validate(req, res)) return;

  const { resetToken, password, passwordConfirm } = req.body;

  try {
    if (password !== passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'Passwords do not match' });
    }

    let decoded;
    try {
      decoded = jwt.verify(resetToken, process.env.JWT_SECRET);
    } catch {
      return res.status(400).json({ status: 'error', message: 'Invalid or expired reset token. Please start over.' });
    }

    if (decoded.purpose !== 'password_reset') {
      return res.status(400).json({ status: 'error', message: 'Invalid reset token.' });
    }

    const hashedPassword = await bcrypt.hash(password, 12);
    const user = await prisma.user.update({
      where: { id: decoded.id },
      data: { password: hashedPassword },
    });

    console.log(`🔐 Password reset for user ${user.email}`);
    createSendToken(user, 200, res);
  } catch (error) {
    console.error('Reset password error:', error);
    res.status(500).json({ status: 'error', message: 'Password reset failed. Please try again.' });
  }
};