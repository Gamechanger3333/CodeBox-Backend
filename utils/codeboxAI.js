const Groq = require('groq-sdk');
require('dotenv').config();

// ============================================================
// CODEBOX AI — Powered by Groq (Llama 3.3 70B)
// ============================================================
// Groq provides blazing-fast inference on open-source models.
// We use llama-3.3-70b-versatile for the main chat (best quality)
// and llama-3.1-8b-instant for lightweight tasks like title gen.
// ============================================================

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

const CODEBOX_SYSTEM_PROMPT = `You are CodeBox AI — a world-class coding assistant for software developers.

YOUR IDENTITY & PURPOSE:
You are an expert in all programming languages, frameworks, libraries, tools, and software engineering concepts. Your mission is to help developers write better code, solve complex problems, learn faster, and build amazing software.

YOUR EXPERTISE:
- All major programming languages: Python, JavaScript, TypeScript, Java, C++, C#, Go, Rust, Ruby, PHP, Swift, Kotlin, Dart, and more
- Web frameworks: React, Next.js, Vue, Angular, Node.js, Express, Django, FastAPI, Laravel, Spring Boot, Rails
- Mobile: React Native, Flutter, iOS (Swift/ObjC), Android (Kotlin/Java)  
- Databases: PostgreSQL, MySQL, MongoDB, Redis, SQLite, Prisma, TypeORM, Mongoose
- Cloud & DevOps: AWS, GCP, Azure, Docker, Kubernetes, CI/CD, Vercel, Railway, Heroku
- AI/ML: PyTorch, TensorFlow, Hugging Face, LangChain, OpenAI API, Groq API
- Tools: Git, GitHub Actions, Webpack, Vite, ESLint, Prettier, Jest, Pytest

RESPONSE STYLE RULES:
1. ALWAYS use proper markdown formatting
2. Wrap ALL code in fenced code blocks with language tags: \`\`\`python, \`\`\`javascript, etc.
3. Be direct — give the solution first, then explain
4. Break complex answers into clear sections
5. Highlight important warnings or gotchas with ⚠️
6. Use 💡 for tips and best practices
7. Use ✅ for correct approaches, ❌ for anti-patterns
8. Keep responses focused — no filler, no padding

WHAT YOU HELP WITH:
✅ Debugging and fixing errors
✅ Code reviews and improvement suggestions
✅ Explaining concepts with practical examples
✅ Architecture and design patterns
✅ Performance optimization
✅ Security best practices
✅ Learning new technologies
✅ Writing tests
✅ API design and integration
✅ Database queries and schema design
✅ Algorithm challenges and interview prep
✅ Deployment and DevOps

WHAT YOU DO NOT DO:
❌ Generate malware, exploits, or security attack tools
❌ Help with academic dishonesty or plagiarism
❌ Answer questions completely unrelated to programming/tech

If a user asks something off-topic, respond:
"I'm CodeBox AI, specialized in software development. I can help with coding questions, debugging, architecture, and all things tech! What are you building?"`;

/**
 * Generate a coding-focused AI response using Groq (Llama 3.3 70B)
 * @param {Array} messages - Array of {sender, content} message history
 * @returns {string} AI response
 */
exports.getCodeBoxAIResponse = async (messages) => {
  // Convert our message format to OpenAI-compatible format
  const formattedMessages = messages.map(msg => ({
    role: msg.sender === 'user' ? 'user' : 'assistant',
    content: msg.content,
  }));

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages: [
      { role: 'system', content: CODEBOX_SYSTEM_PROMPT },
      ...formattedMessages,
    ],
    temperature: 0.7,
    max_tokens: 4096,
  });

  return completion.choices[0]?.message?.content || 'Sorry, I could not generate a response.';
};

/**
 * Analyze uploaded code using Groq
 * @param {string} code - The code content
 * @param {string} filename - The filename for context
 * @returns {string} Analysis response
 */
exports.analyzeCode = async (code, filename) => {
  const prompt = `Analyze the following code from file "${filename}":

\`\`\`
${code}
\`\`\`

Please provide:
1. **What this code does** — a brief summary
2. **Code quality** — structure, readability, and style
3. **Potential bugs or issues** — anything that could cause problems
4. **Security concerns** — any vulnerabilities
5. **Performance improvements** — optimization opportunities
6. **Best practice suggestions** — how to improve it

Be specific and actionable.`;

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages: [
      { role: 'system', content: CODEBOX_SYSTEM_PROMPT },
      { role: 'user', content: prompt },
    ],
    temperature: 0.5,
    max_tokens: 2048,
  });

  return completion.choices[0]?.message?.content || 'Analysis failed.';
};

/**
 * Generate a conversation title using lightweight Groq model
 * @param {string} firstMessage - The user's first message
 * @returns {string} A short title for the conversation
 */
exports.generateConversationTitle = async (firstMessage) => {
  const completion = await groq.chat.completions.create({
    model: 'llama-3.1-8b-instant', // Lightweight model for fast title gen
    messages: [
      {
        role: 'user',
        content: `Generate a short, descriptive title (max 5 words) for a coding conversation that starts with: "${firstMessage}"

Rules:
- Must be relevant to the coding topic
- No quotes, no punctuation at the end
- Capitalize first word only
- Examples: "Python list comprehension help", "React useState hook error", "SQL join optimization"

Return ONLY the title, nothing else.`,
      },
    ],
    temperature: 0.3,
    max_tokens: 20,
  });

  return completion.choices[0]?.message?.content?.trim() || 'New conversation';
};

/**
 * Detect programming language from a code snippet
 * @param {string} code - Code snippet
 * @returns {string} Language name
 */
exports.detectLanguage = async (code) => {
  const completion = await groq.chat.completions.create({
    model: 'llama-3.1-8b-instant',
    messages: [
      {
        role: 'user',
        content: `What programming language is this code written in? Reply with ONLY the language name (e.g. "Python", "JavaScript", "Rust"). Code:\n\n${code.substring(0, 500)}`,
      },
    ],
    temperature: 0,
    max_tokens: 10,
  });

  return completion.choices[0]?.message?.content?.trim() || 'Unknown';
};
