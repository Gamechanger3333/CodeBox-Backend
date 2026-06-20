// controllers/Projectanalyzer.js
// Project analysis logic — uses the shared groqClient singleton.
// Never create a new Groq() here; import it from utils/groqClient.

const groq = require('../utils/groqClient');

// File extensions to include in analysis (skip binaries, lock files, etc.)
const ALLOWED_EXTENSIONS = new Set([
  '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
  '.py', '.rb', '.php', '.go', '.rs', '.java', '.kt', '.swift',
  '.cs', '.cpp', '.c', '.h', '.hpp',
  '.html', '.htm', '.css', '.scss', '.sass', '.less',
  '.vue', '.svelte', '.astro',
  '.json', '.yaml', '.yml', '.toml', '.env.example',
  '.md', '.mdx', '.txt', '.sh', '.bash', '.zsh',
  '.sql', '.prisma', '.graphql', '.gql',
  '.xml', '.csv',
  '.dockerfile', '.dockerignore', '.gitignore', '.eslintrc',
  '.prettierrc', '.babelrc', '.env.local.example',
]);

const SKIP_DIRS = new Set([
  'node_modules', '.git', '.next', 'dist', 'build', 'out',
  '.cache', 'coverage', '.nyc_output', '__pycache__', '.pytest_cache',
  'venv', '.venv', 'env', '.env', 'vendor',
  '.idea', '.vscode', '.DS_Store',
]);

const SKIP_FILES = new Set([
  'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
  'poetry.lock', 'Pipfile.lock', 'composer.lock',
  'Cargo.lock', 'go.sum', '.DS_Store', 'thumbs.db',
]);

const MAX_FILE_SIZE = 20 * 1024;  // 20 KB per file
const MAX_TOTAL_CHARS = 28000;    // ~7k tokens — fits Groq free tier (12k TPM limit)

function shouldIncludeFile(filePath) {
  const parts = filePath.split('/');
  const filename = parts[parts.length - 1];

  if (filename.startsWith('.') && !ALLOWED_EXTENSIONS.has('.' + filename.split('.').slice(1).join('.'))) {
    const allowedDotfiles = ['.env.example', '.env.local.example', '.gitignore', '.eslintrc', '.prettierrc', '.babelrc', '.dockerignore'];
    if (!allowedDotfiles.some(d => filename.endsWith(d.replace(/^\./, '')))) return false;
  }

  for (const part of parts.slice(0, -1)) {
    if (SKIP_DIRS.has(part)) return false;
  }

  if (SKIP_FILES.has(filename)) return false;

  const ext = '.' + filename.split('.').slice(1).join('.');
  const simpleExt = filename.includes('.') ? '.' + filename.split('.').pop() : '';
  return ALLOWED_EXTENSIONS.has(ext) || ALLOWED_EXTENSIONS.has(simpleExt);
}

function buildFileTree(filePaths) {
  const tree = {};
  for (const p of filePaths) {
    const parts = p.split('/');
    let node = tree;
    for (const part of parts) {
      if (!node[part]) node[part] = {};
      node = node[part];
    }
  }

  const lines = [];
  function render(node, prefix = '') {
    const keys = Object.keys(node).sort((a, b) => {
      const aIsDir = Object.keys(node[a]).length > 0;
      const bIsDir = Object.keys(node[b]).length > 0;
      if (aIsDir && !bIsDir) return -1;
      if (!aIsDir && bIsDir) return 1;
      return a.localeCompare(b);
    });
    keys.forEach((key, i) => {
      const last = i === keys.length - 1;
      const connector = last ? '└── ' : '├── ';
      const isDir = Object.keys(node[key]).length > 0;
      lines.push(prefix + connector + key + (isDir ? '/' : ''));
      if (isDir) render(node[key], prefix + (last ? '    ' : '│   '));
    });
  }
  render(tree);
  return lines.join('\n');
}

async function extractProjectFiles(zipBuffer) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(zipBuffer);

  const allFiles = [];
  const promises = [];

  zip.forEach((relativePath, zipEntry) => {
    if (zipEntry.dir) return;
    if (!shouldIncludeFile(relativePath)) return;

    promises.push(
      zipEntry.async('uint8array').then(data => {
        if (data.length > MAX_FILE_SIZE) return;
        const text = new TextDecoder('utf-8', { fatal: false }).decode(data);
        const nonPrintable = (text.match(/[\x00-\x08\x0e-\x1f\x7f-\x9f]/g) || []).length;
        if (nonPrintable / text.length > 0.1) return;
        const cleanPath = relativePath.replace(/^[^/]+\//, '');
        if (cleanPath) allFiles.push({ path: cleanPath, content: text.trim() });
      })
    );
  });

  await Promise.all(promises);
  allFiles.sort((a, b) => a.path.localeCompare(b.path));

  let totalChars = 0;
  const includedFiles = [];
  const skippedFiles = [];

  const priority = (p) => {
    if (p.match(/^(README|package\.json|prisma\/schema|app\.js|index\.(js|ts)|main\.(py|go|rs))/i)) return 0;
    if (p.match(/\.(json|yaml|yml|toml|prisma|sql)$/)) return 1;
    if (p.match(/\.(js|ts|jsx|tsx|py|go|rs|java)$/)) return 2;
    return 3;
  };
  allFiles.sort((a, b) => priority(a.path) - priority(b.path));

  for (const file of allFiles) {
    if (totalChars + file.content.length > MAX_TOTAL_CHARS) {
      skippedFiles.push(file.path);
      continue;
    }
    includedFiles.push(file);
    totalChars += file.content.length;
  }

  const fileTree = buildFileTree(allFiles.map(f => f.path));
  return {
    fileTree,
    files: includedFiles,
    stats: {
      total: allFiles.length,
      analyzed: includedFiles.length,
      skipped: skippedFiles.length,
      totalChars,
    },
  };
}

function buildProjectContext(fileTree, files) {
  let context = `PROJECT FILE STRUCTURE:\n\`\`\`\n${fileTree}\n\`\`\`\n\n`;
  context += `=== FILE CONTENTS ===\n\n`;
  for (const file of files) {
    const ext = file.path.split('.').pop();
    context += `--- FILE: ${file.path} ---\n\`\`\`${ext}\n${file.content}\n\`\`\`\n\n`;
  }
  return context;
}

const PROJECT_ANALYST_SYSTEM_PROMPT = `You are CodeBox Project Analyst — an expert software architect and senior engineer who performs thorough, actionable codebase reviews.

You receive a complete project codebase and analyze it holistically, like a senior engineer doing a serious code review before a team handoff or production deployment.

YOUR ANALYSIS STYLE:
- Be specific: reference actual file names, line patterns, and code examples from the project
- Be actionable: every issue you raise should have a clear next step
- Prioritize ruthlessly: surface the most impactful findings first
- Be honest: don't pad with praise — focus on what matters
- Use markdown formatting with clear headers, code blocks with language tags, and bullet points
- Use ⚠️ for critical issues, 💡 for improvements, ✅ for strengths, 🔴 for security/bugs, 🟡 for warnings`;

exports.analyzeProject = async (fileTree, files) => {
  const projectContext = buildProjectContext(fileTree, files);

  const analysisPrompt = `${projectContext}

---

Perform a comprehensive project analysis. Structure your response with these exact sections:

## 📁 Project Overview
What this project is, its purpose, tech stack, and architecture pattern.

## 🏗️ Architecture & Structure
How the code is organized. Is the structure clean and scalable?

## 🔴 Critical Issues
Bugs, security vulnerabilities, data loss risks, or anything that could cause production failures.

## ⚠️ Code Quality
Inconsistencies, anti-patterns, technical debt, or maintainability problems.

## 🔒 Security Analysis
Authentication, authorization, input validation, secrets handling, SQL injection, XSS, CSRF risks.

## ⚡ Performance
Inefficient queries, missing indexes, unnecessary re-renders, memory leaks, or scalability concerns.

## 💡 Improvements & Recommendations
The top 5 most impactful things the team should do next, in priority order.

## ✅ Strengths
What the codebase does well — be genuine, not generic.`;

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages: [
      { role: 'system', content: PROJECT_ANALYST_SYSTEM_PROMPT },
      { role: 'user', content: analysisPrompt },
    ],
    temperature: 0.4,
    max_tokens: 2000,
  });

  return completion.choices[0]?.message?.content || 'Analysis failed.';
};

exports.askAboutProject = async (fileTree, files, conversationHistory, userQuestion) => {
  const projectContext = buildProjectContext(fileTree, files);

  const messages = [
    { role: 'system', content: PROJECT_ANALYST_SYSTEM_PROMPT },
    {
      role: 'user',
      content: `Here is the complete project codebase for reference:\n\n${projectContext}\n\n---\nI have reviewed this project. Now answer my questions about it.`,
    },
    {
      role: 'assistant',
      content: "I've reviewed the entire codebase. Ask me anything about this project — bugs, refactoring, architecture, adding features, or specific files.",
    },
    ...conversationHistory.map(m => ({ role: m.role, content: m.content })),
    { role: 'user', content: userQuestion },
  ];

  const completion = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    messages,
    temperature: 0.5,
    max_tokens: 1500,
  });

  return completion.choices[0]?.message?.content || 'Could not generate response.';
};

exports.extractProjectFiles = extractProjectFiles;
exports.buildFileTree = buildFileTree;
exports.buildProjectContext = buildProjectContext;