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

// Use structured 'combined' logs in production, readable 'dev' format locally.
if (process.env.NODE_ENV === 'production') {
  app.use(morgan('combined'));
} else {
  app.use(morgan('dev'));
}

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
  origin: process.env.FRONTEND_URL || 'http://localhost:3000',
  credentials: true,
}));

app.use(cookieParser());

// Auth-specific rate limiting — covers OTP brute-forcing too.
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

// 404 handler
app.use((req, res) => {
  res.status(404).json({ status: 'error', message: 'Route not found' });
});

// Global error handler — never leak internal error details to the client in production.
// Exception: errors we explicitly mark as `expose = true` (e.g. missing
// third-party API key) have a message that's safe and useful to show the
// user as-is, even in production.
app.use((err, req, res, next) => {
  console.error(err.stack);
  const isProd = process.env.NODE_ENV === 'production';
  const safeToShow = isProd && (err.expose === true || (err.status && err.status < 500));
  res.status(err.status || 500).json({
    status: 'error',
    message: (!isProd || safeToShow) ? (err.message || 'Internal Server Error') : 'Something went wrong. Please try again.',
  });
});

const PORT = process.env.PORT || 5000;

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`🚀 CodeBox API running on http://localhost:${PORT}`);
  });
}

module.exports = app;