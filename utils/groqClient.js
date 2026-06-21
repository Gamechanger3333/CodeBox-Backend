// utils/groqClient.js
// Single Groq SDK instance shared across all AI utilities.
// Instantiating multiple clients wastes memory and makes API key
// configuration inconsistent — one require, one object.
//
// IMPORTANT: this client is created LAZILY. If GROQ_API_KEY is missing,
// the error is thrown only when an AI feature is actually used — not at
// server boot. Throwing at require() time would crash the entire API
// (including unrelated features like auth and snippets) just because one
// third-party key was missing or rotated.

const Groq = require('groq-sdk');
require('dotenv').config();

let groqInstance = null;

function getGroqClient() {
  if (groqInstance) return groqInstance;

  if (!process.env.GROQ_API_KEY) {
    const err = new Error('AI features are temporarily unavailable. Please try again later.');
    err.status = 503;
    err.expose = true;
    err.code = 'GROQ_API_KEY_MISSING';
    // Log the real cause server-side without leaking it to the client.
    console.error('GROQ_API_KEY environment variable is not set. Check your .env file.');
    throw err;
  }

  groqInstance = new Groq({ apiKey: process.env.GROQ_API_KEY });
  return groqInstance;
}

// Proxy so existing call sites (`groq.chat.completions.create(...)`) keep
// working unchanged — the client is only constructed on first real access.
module.exports = new Proxy({}, {
  get(_target, prop) {
    const client = getGroqClient();
    return client[prop];
  },
});
