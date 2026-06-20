const jwt = require('jsonwebtoken');

const authMiddleware = (req, res, next) => {
  // Try Authorization header first, then fall back to cookie
  let token;

  const authHeader = req.headers.authorization;
  if (authHeader && authHeader.startsWith('Bearer ')) {
    token = authHeader.split(' ')[1];
  } else if (req.cookies && req.cookies.token) {
    token = req.cookies.token;
  }

  if (!token) {
    return res.status(401).json({ error: 'Token missing' });
  }

  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);

    // Reset tokens are issued with a `purpose` claim and are only meant to
    // authorize POST /reset-password for a short window. They must never be
    // accepted as a general-purpose API credential.
    if (decoded.purpose) {
      return res.status(403).json({ error: 'Invalid or expired token' });
    }

    req.user = decoded;
    next();
  } catch (error) {
    return res.status(403).json({ error: 'Invalid or expired token' });
  }
};

module.exports = authMiddleware;