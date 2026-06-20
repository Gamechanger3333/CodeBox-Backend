// utils/groqClient.js
// Single Groq SDK instance shared across all AI utilities.
// Instantiating multiple clients wastes memory and makes API key
// configuration inconsistent — one require, one object.

const Groq = require('groq-sdk');
require('dotenv').config();

if (!process.env.GROQ_API_KEY) {
  throw new Error('GROQ_API_KEY environment variable is not set. Check your .env file.');
}

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

module.exports = groq;