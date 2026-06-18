const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const prisma = require('../models/prismaClient');
const { sendPasswordResetOTP, generateOTP } = require('../utils/emailService');

// ============================================================
// TOKEN HELPERS
// ============================================================

const signToken = (id) => {
  return jwt.sign({ id }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN || '7d',
  });
};

const createSendToken = (user, statusCode, res) => {
  const token = signToken(user.id);
  const cookieExpiresIn = parseInt(process.env.JWT_COOKIE_EXPIRES_IN || '7');

  res.cookie('token', token, {
    expires: new Date(Date.now() + cookieExpiresIn * 24 * 60 * 60 * 1000),
    httpOnly: false, // false so js-cookie can read it on the frontend
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
  });

  const { password, otpCode, otpExpiry, otpAttempts, ...userData } = user;
  res.status(statusCode).json({ status: 'success', token, data: { user: userData } });
};

// ============================================================
// SIGNUP
// ============================================================

exports.signup = async (req, res) => {
  const { name, email, password, passwordConfirm } = req.body;

  try {
    if (!name || !email || !password || !passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'All fields are required' });
    }

    if (password !== passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'Passwords do not match' });
    }

    if (password.length < 8) {
      return res.status(400).json({ status: 'error', message: 'Password must be at least 8 characters' });
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

// ============================================================
// LOGIN
// ============================================================

exports.login = async (req, res, next) => {
  const { email, password } = req.body;

  try {
    if (!email || !password) {
      return res.status(400).json({ status: 'error', message: 'Email and password are required' });
    }

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

// ============================================================
// LOGOUT
// ============================================================

exports.logout = (req, res) => {
  res.cookie('token', '', {
    expires: new Date(Date.now() + 10 * 1000),
    httpOnly: false,
  });
  res.status(200).json({ status: 'success', message: 'Logged out successfully' });
};

// ============================================================
// FORGOT PASSWORD — Step 1: Send OTP
// ============================================================

exports.forgotPassword = async (req, res) => {
  const { email } = req.body;

  try {
    if (!email) {
      return res.status(400).json({ status: 'error', message: 'Email is required' });
    }

    const user = await prisma.user.findUnique({ where: { email } });

    // Always return success to prevent email enumeration attacks
    if (!user) {
      return res.status(200).json({
        status: 'success',
        message: 'If an account with this email exists, you will receive an OTP shortly.',
      });
    }

    // Generate OTP
    const otp = generateOTP();
    const otpExpiry = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes

    // Save hashed OTP to DB (hash it for security)
    const hashedOtp = await bcrypt.hash(otp, 10);
    await prisma.user.update({
      where: { email },
      data: {
        otpCode: hashedOtp,
        otpExpiry,
        otpAttempts: 0,
      },
    });

    // Send OTP email
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

// ============================================================
// VERIFY OTP — Step 2: Confirm OTP is valid
// ============================================================

exports.verifyOtp = async (req, res) => {
  const { email, otp } = req.body;

  try {
    if (!email || !otp) {
      return res.status(400).json({ status: 'error', message: 'Email and OTP are required' });
    }

    const user = await prisma.user.findUnique({ where: { email } });

    if (!user || !user.otpCode || !user.otpExpiry) {
      return res.status(400).json({ status: 'error', message: 'No active OTP found. Please request a new one.' });
    }

    // Check if OTP is expired
    if (new Date() > user.otpExpiry) {
      await prisma.user.update({
        where: { email },
        data: { otpCode: null, otpExpiry: null, otpAttempts: 0 },
      });
      return res.status(400).json({ status: 'error', message: 'OTP has expired. Please request a new one.' });
    }

    // Check attempts (max 5 to prevent brute force)
    if (user.otpAttempts >= 5) {
      await prisma.user.update({
        where: { email },
        data: { otpCode: null, otpExpiry: null, otpAttempts: 0 },
      });
      return res.status(429).json({ status: 'error', message: 'Too many failed attempts. Please request a new OTP.' });
    }

    // Verify OTP
    const isValid = await bcrypt.compare(otp, user.otpCode);

    if (!isValid) {
      // Increment attempts
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

    // OTP is valid — issue a short-lived reset token
    const resetToken = jwt.sign(
      { id: user.id, email: user.email, purpose: 'password_reset' },
      process.env.JWT_SECRET,
      { expiresIn: '15m' }
    );

    // Clear OTP from DB (one-time use)
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

// ============================================================
// RESET PASSWORD — Step 3: Set new password
// ============================================================

exports.resetPassword = async (req, res) => {
  const { resetToken, password, passwordConfirm } = req.body;

  try {
    if (!resetToken || !password || !passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'All fields are required' });
    }

    if (password !== passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'Passwords do not match' });
    }

    if (password.length < 8) {
      return res.status(400).json({ status: 'error', message: 'Password must be at least 8 characters' });
    }

    // Verify reset token
    let decoded;
    try {
      decoded = jwt.verify(resetToken, process.env.JWT_SECRET);
    } catch {
      return res.status(400).json({ status: 'error', message: 'Invalid or expired reset token. Please start over.' });
    }

    if (decoded.purpose !== 'password_reset') {
      return res.status(400).json({ status: 'error', message: 'Invalid reset token.' });
    }

    // Update password
    const hashedPassword = await bcrypt.hash(password, 12);
    const user = await prisma.user.update({
      where: { id: decoded.id },
      data: { password: hashedPassword },
    });

    console.log(`🔐 Password reset for user ${user.email}`);

    // Log the user in with new credentials
    createSendToken(user, 200, res);
  } catch (error) {
    console.error('Reset password error:', error);
    res.status(500).json({ status: 'error', message: 'Password reset failed. Please try again.' });
  }
};
