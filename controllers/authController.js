const jwt = require('jsonwebtoken');
const prisma = require('../models/prismaClient'); // Assuming prismaClient is correctly configured
    const bcrypt = require('bcrypt');

    
const signToken = id => {
    return jwt.sign({ id }, process.env.JWT_SECRET, {
      expiresIn: process.env.JWT_EXPIRES_IN
    });
  };
  
  const createSendToken = (user, statusCode, res) => {
    const token = signToken(user.id);

    // Calculate cookie expiration time
    const cookieExpiresIn = process.env.JWT_COOKIE_EXPIRES_IN || 90; // Default to 90 days if env variable is not set
    const cookieOptions = {
        expires: new Date(Date.now() + cookieExpiresIn * 24 * 60 * 60 * 1000) // Convert days to milliseconds
    };

if (process.env.NODE_ENV === 'production') {
    cookieOptions.secure = true;
}

    res.cookie('jwt', token, cookieOptions);

    // Remove sensitive data from user object
    const { password, ...userData } = user;

    res.status(statusCode).json({ status: 'success', token, data: { user: userData } });
};
  
  exports.signup = async (req, res) => {
  const { name, email, password, passwordConfirm } = req.body;

  try {
    if (password !== passwordConfirm) {
      return res.status(400).json({
        status: 'error',
        message: 'Passwords do not match'
      });
    }

    const existingUser = await prisma.user.findUnique({ where: { email } });

    if (existingUser) {
      return res.status(400).json({
        status: 'error',
        message: 'Email already exists'
      });
    }

    const hashedPassword = await bcrypt.hash(password, 12);

    const newUser = await prisma.user.create({
      data: {
        name,
        email,
        password: hashedPassword
      }
    });

    createSendToken(newUser, 201, res);

  } catch (error) {
    console.error("Signup error:", error);
    res.status(500).json({
      status: 'error',
      message: error.message
    });
  }
};
  
  exports.login = async (req, res, next) => {
    const { email, password } = req.body;

    try {
        // Find user by email
        const user = await prisma.user.findUnique({ where: { email } });

        if (!user) {
            // User not found
            return res.status(401).json({ status: 'error', message: 'Incorrect email or password' });
        }



// ✅ Fixed
const passwordsMatch = await bcrypt.compare(password, user.password);        if (!passwordsMatch) {
            return res.status(401).json({ status: 'error', message: 'Incorrect email or password' });
        }

        // Send JWT token if login successful
        createSendToken(user, 200, res);

    } catch (error) {
        next(error); // Forward error to error handling middleware
    }
};
  
  exports.logout = (req, res) => {
    res.cookie('jwt', 'loggedout', {
      expires: new Date(Date.now() + 10 * 1000)
    });
    res.status(200).json({ status: 'success' , message : 'cookies cleared successfully!' });
  };
  
  