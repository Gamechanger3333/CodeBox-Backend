require('dotenv').config();

module.exports = {
  port: process.env.PORT || 5000,
  togetherAIKey: process.env.TOGETHER_AI_API_KEY,
  togetherAIUrl: 'http://localhost:3000/api/send_message',
  databaseUrl: process.env.DATABASE_URL,
  SECRET_KEY: process.env.JWT_SECRET
};