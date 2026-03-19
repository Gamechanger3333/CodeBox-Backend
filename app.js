const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const morgan = require('morgan');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

const conversationRoutes = require('./routes/conversationRoutes');
const authRoutes = require('./routes/authRoutes');

const app = express();

// ✅ Security headers
app.use(helmet());

// ✅ Request logging
app.use(morgan('dev'));

// ✅ Rate limiting on auth routes (max 20 requests per 15 min)
const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 200,
  message: { status: 'error', message: 'Too many requests, please try again later.' },
});

// ✅ Body parsing
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ✅ CORS
app.use(cors({
  origin: 'http://localhost:3000',
  credentials: true,
}));

// ✅ Cookie parsing
app.use(cookieParser());

// Routes
// ✅ With this
app.use('/api/login', authLimiter);
app.use('/api/signup', authLimiter);
app.use('/api', authRoutes);
app.use('/api', conversationRoutes);

// ✅ Global error handler
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(err.status || 500).json({
    status: 'error',
    message: err.message || 'Internal Server Error',
  });
});

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});