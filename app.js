const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const morgan = require('morgan');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

const conversationRoutes = require('./routes/conversationRoutes');
const authRoutes = require('./routes/authRoutes');

const app = express();

app.use(helmet());
app.use(morgan('dev'));

const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 20,
  message: { status: 'error', message: 'Too many requests, please try again later.' },
});

const apiLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 60,
  message: { status: 'error', message: 'Rate limit exceeded. Please slow down.' },
});

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

app.use(cors({
  origin: process.env.FRONTEND_URL || 'http://localhost:3001',
  credentials: true,
}));

app.use(cookieParser());

// Routes
// authLimiter covers every auth-related endpoint, including the OTP flow,
// not just login/signup — OTP brute-forcing needs the same strict ceiling.
app.use('/api/login', authLimiter);
app.use('/api/signup', authLimiter);
app.use('/api/forgot-password', authLimiter);
app.use('/api/verify-otp', authLimiter);
app.use('/api/reset-password', authLimiter);
app.use('/api', apiLimiter);
app.use('/api', authRoutes);
app.use('/api', conversationRoutes);

// Health check
app.get('/health', (req, res) => res.json({ status: 'ok', service: 'CodeBox API' }));

// 404 handler — must come after all routes
app.use((req, res) => {
  res.status(404).json({ status: 'error', message: 'Route not found' });
});

// Global error handler
// Never leak err.message to the client in production — it can expose
// internal details (Prisma errors, file paths, etc). Full detail still
// goes to the server logs via console.error.
app.use((err, req, res, next) => {
  console.error(err.stack);
  const isProd = process.env.NODE_ENV === 'production';
  res.status(err.status || 500).json({
    status: 'error',
    message: isProd ? 'Something went wrong. Please try again.' : (err.message || 'Internal Server Error'),
  });
});

const PORT = process.env.PORT || 5000;

// app.listen() works fine on traditional hosts (Railway, Render, a VPS, etc).
// If you deploy to Vercel's serverless runtime instead, Vercel invokes the
// exported `app` directly and app.listen() is simply never called — safe
// either way, but module.exports is required for Vercel to work at all.
if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`🚀 CodeBox API running on http://localhost:${PORT}`);
  });
}

module.exports = app;