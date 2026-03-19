const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const prisma = require('../models/prismaClient');

const signToken = (id) => {
  return jwt.sign({ id }, process.env.JWT_SECRET, {
    expiresIn: process.env.JWT_EXPIRES_IN,
  });
};

const createSendToken = (user, statusCode, res) => {
  const token = signToken(user.id);

  const cookieExpiresIn = process.env.JWT_COOKIE_EXPIRES_IN || 90;

  // ✅ httpOnly: false so js-cookie can read it on the frontend
  res.cookie('token', token, {
    expires: new Date(Date.now() + cookieExpiresIn * 24 * 60 * 60 * 1000),
    httpOnly: false,
    secure: false, // false for localhost
    sameSite: 'lax',
  });

  const { password, ...userData } = user;
  res.status(statusCode).json({ status: 'success', token, data: { user: userData } });
};

exports.signup = async (req, res) => {
  const { name, email, password, passwordConfirm } = req.body;

  try {
    if (password !== passwordConfirm) {
      return res.status(400).json({ status: 'error', message: 'Passwords do not match' });
    }

    const existingUser = await prisma.user.findUnique({ where: { email } });
    if (existingUser) {
      return res.status(400).json({ status: 'error', message: 'Email already exists' });
    }

    const hashedPassword = await bcrypt.hash(password, 12);
    const newUser = await prisma.user.create({
      data: { name, email, password: hashedPassword },
    });

    createSendToken(newUser, 201, res);
  } catch (error) {
    console.error('Signup error:', error);
    res.status(500).json({ status: 'error', message: error.message });
  }
};

exports.login = async (req, res, next) => {
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

exports.logout = (req, res) => {
  res.cookie('token', '', {
    expires: new Date(Date.now() + 10 * 1000),
    httpOnly: false,
  });
  res.status(200).json({ status: 'success', message: 'Logged out successfully' });
};