const { GoogleGenerativeAI } = require('@google/generative-ai');
require('dotenv').config();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

// ============================================================
// CODEBOX AI SYSTEM INSTRUCTIONS
// ============================================================
// CodeBox is an AI-powered coding assistant platform built for
// developers. Users are programmers who need help with:
//   - Debugging code and fixing errors
//   - Learning new languages, frameworks, and tools
//   - Code reviews and best practices
//   - Algorithms, data structures, architecture decisions
//   - Performance optimization
//   - DevOps, deployment, databases
//   - Open source libraries and APIs
//
// The AI must:
//   1. Always respond with accurate, executable code examples
//   2. Format code in proper markdown code blocks with language tags
//   3. Explain WHY, not just WHAT — teach the developer
//   4. Be concise but thorough — developers value efficiency
//   5. Default to modern best practices
//   6. Flag deprecated patterns or security concerns proactively
//   7. Adapt to the user's skill level based on their questions
//   8. Stay on-topic: programming, tech, software engineering
//   9. For off-topic questions, politely redirect to coding topics
//  10. Never produce harmful, malicious, or exploitative code
// ============================================================

const CODEBOX_SYSTEM_PROMPT = `You are CodeBox AI — a world-class coding assistant for software developers.

YOUR IDENTITY & PURPOSE:
You are an expert in all programming languages, frameworks, libraries, tools, and software engineering concepts. Your mission is to help developers write better code, solve complex problems, learn faster, and build amazing software.

YOUR EXPERTISE:
- All major programming languages: Python, JavaScript, TypeScript, Java, C++, C#, Go, Rust, Ruby, PHP, Swift, Kotlin, Dart, and more
- Web frameworks: React, Next.js, Vue, Angular, Node.js, Express, Django, FastAPI, Laravel, Spring Boot, Rails
- Mobile: React Native, Flutter, iOS (Swift/ObjC), Android (Kotlin/Java)  
- Databases: PostgreSQL, MySQL, MongoDB, Redis, SQLite, Prisma, TypeORM, Mongoose
- Cloud & DevOps: AWS, GCP, Azure, Docker, Kubernetes, CI/CD, Vercel, Railway, Heroku
- AI/ML: PyTorch, TensorFlow, Hugging Face, LangChain, OpenAI API, Gemini API
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
✅ Debugging and fixing errors (paste your error and code!)
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
"I'm CodeBox AI, specialized in software development. I can help with coding questions, debugging, architecture, and all things tech! What are you building?"

IMPORTANT: You are a coding assistant, not a general-purpose AI. Keep every response focused on helping the developer succeed.`;

/**
 * Generate a coding-focused AI response using Gemini
 * @param {Array} messages - Array of {role, content} message history
 * @returns {string} AI response
 */
exports.getCodeBoxAIResponse = async (messages) => {
  const model = genAI.getGenerativeModel({ 
    model: "gemini-2.0-flash",
    systemInstruction: CODEBOX_SYSTEM_PROMPT,
  });

  // Build conversation history for Gemini
  const history = messages.slice(0, -1).map(msg => ({
    role: msg.sender === 'user' ? 'user' : 'model',
    parts: [{ text: msg.content }],
  }));

  const lastMessage = messages[messages.length - 1];

  const chat = model.startChat({ history });
  const result = await chat.sendMessage(lastMessage.content);
  return result.response.text();
};

/**
 * Analyze uploaded code file and return insights
 * @param {string} code - The code content
 * @param {string} filename - The filename for context
 * @returns {string} Analysis response
 */
exports.analyzeCode = async (code, filename) => {
  const model = genAI.getGenerativeModel({ 
    model: "gemini-2.0-flash",
    systemInstruction: CODEBOX_SYSTEM_PROMPT,
  });

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

  const result = await model.generateContent(prompt);
  return result.response.text();
};

/**
 * Generate a conversation title from the first message
 * @param {string} firstMessage - The user's first message
 * @returns {string} A short title for the conversation
 */
exports.generateConversationTitle = async (firstMessage) => {
  const model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });
  
  const prompt = `Generate a short, descriptive title (max 5 words) for a coding conversation that starts with this message: "${firstMessage}"

Rules:
- Must be relevant to the coding topic
- No quotes, no punctuation at the end
- Capitalize first word only
- Examples: "Python list comprehension help", "React useState hook error", "SQL join optimization", "Docker container setup"

Return ONLY the title, nothing else.`;

  const result = await model.generateContent(prompt);
  return result.response.text().trim();
};

/**
 * Detect programming language from a code snippet
 * @param {string} code - Code snippet
 * @returns {string} Language name
 */
exports.detectLanguage = async (code) => {
  const model = genAI.getGenerativeModel({ model: "gemini-2.0-flash" });
  const prompt = `What programming language is this code written in? Reply with ONLY the language name (e.g. "Python", "JavaScript", "Rust"). Code:\n\n${code.substring(0, 500)}`;
  const result = await model.generateContent(prompt);
  return result.response.text().trim();
};
