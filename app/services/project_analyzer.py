"""Project analysis: unpack a ZIP, build the file tree, ask the LLM for a review."""
from __future__ import annotations

import io
import re
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app import prompts
from app.services import groq_client

ALLOWED_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".py", ".rb", ".php", ".go", ".rs", ".java", ".kt", ".swift",
    ".cs", ".cpp", ".c", ".h", ".hpp",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte", ".astro",
    ".json", ".yaml", ".yml", ".toml", ".env.example",
    ".md", ".mdx", ".txt", ".sh", ".bash", ".zsh",
    ".sql", ".prisma", ".graphql", ".gql",
    ".xml", ".csv",
    ".dockerfile", ".dockerignore", ".gitignore", ".eslintrc",
    ".prettierrc", ".babelrc", ".env.local.example",
}
SKIP_DIRS = {
    "node_modules", ".git", ".next", "dist", "build", "out",
    ".cache", "coverage", ".nyc_output", "__pycache__", ".pytest_cache",
    "venv", ".venv", "env", ".env", "vendor",
    ".idea", ".vscode", ".DS_Store",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "composer.lock",
    "Cargo.lock", "go.sum", ".DS_Store", "thumbs.db",
}
ALLOWED_DOTFILES = [".env.example", ".env.local.example", ".gitignore", ".eslintrc", ".prettierrc", ".babelrc", ".dockerignore"]

MAX_FILE_SIZE = 20 * 1024  # 20 KB per file
# Groq's on_demand tier caps at 8,000 TPM (input + output). 18,000 chars (~4.5k tokens) keeps
# the one-shot analysis request comfortably below that.
MAX_TOTAL_CHARS = 18_000

_NON_PRINTABLE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")
_PRIORITY_0 = re.compile(r"^(README|package\.json|prisma/schema|app\.js|index\.(js|ts)|main\.(py|go|rs))", re.IGNORECASE)
_PRIORITY_1 = re.compile(r"\.(json|yaml|yml|toml|prisma|sql)$")
_PRIORITY_2 = re.compile(r"\.(js|ts|jsx|tsx|py|go|rs|java)$")

_PUNCT_ORDER = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def js_length(s: str) -> int:
    """JavaScript's String.length counts UTF-16 code units (an emoji = 2). The 18,000-char budget and the
    stats shown in the UI were defined that way, so we count the same way to stay identical."""
    return len(s.encode("utf-16-le")) // 2


def locale_key(s: str):
    """Approximation of JS String.localeCompare (ICU): punctuation < digits < letters, case-insensitive,
    lowercase before uppercase on ties. Only used to keep file ordering stable/readable."""
    primary = []
    for ch in s:
        if ch.isdigit():
            primary.append((2, ch))
        elif ch.isalpha():
            primary.append((3, ch.lower()))
        else:
            primary.append((1, f"{_PUNCT_ORDER.index(ch):03d}" if ch in _PUNCT_ORDER else f"{100 + ord(ch):06d}"))
    return primary, [ch.isupper() for ch in s]


def should_include_file(file_path: str) -> bool:
    parts = file_path.split("/")
    filename = parts[-1]

    if filename.startswith(".") and ("." + ".".join(filename.split(".")[1:])) not in ALLOWED_EXTENSIONS:
        if not any(filename.endswith(d.lstrip(".")) for d in ALLOWED_DOTFILES):
            return False

    if any(part in SKIP_DIRS for part in parts[:-1]):
        return False
    if filename in SKIP_FILES:
        return False

    ext = "." + ".".join(filename.split(".")[1:])
    simple_ext = "." + filename.split(".")[-1] if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS or simple_ext in ALLOWED_EXTENSIONS


def build_file_tree(file_paths: list[str]) -> str:
    tree: dict[str, Any] = {}
    for p in file_paths:
        node = tree
        for part in p.split("/"):
            node = node.setdefault(part, {})

    lines: list[str] = []

    def render(node: dict[str, Any], prefix: str = "") -> None:
        # directories first, then files, each alphabetically
        keys = sorted(node, key=lambda k: (0 if node[k] else 1, locale_key(k)))
        for i, key in enumerate(keys):
            last = i == len(keys) - 1
            is_dir = bool(node[key])
            lines.append(prefix + ("└── " if last else "├── ") + key + ("/" if is_dir else ""))
            if is_dir:
                render(node[key], prefix + ("    " if last else "│   "))

    render(tree)
    return "\n".join(lines)


def _priority(path: str) -> int:
    if _PRIORITY_0.search(path):
        return 0
    if _PRIORITY_1.search(path):
        return 1
    if _PRIORITY_2.search(path):
        return 2
    return 3


def extract_project_files(zip_bytes: bytes) -> dict[str, Any]:
    """Read a ZIP and return {fileTree, files (capped), allFiles (everything readable), stats}.

    Synchronous + CPU bound: call it with asyncio.to_thread() from async code.
    Raises zipfile.BadZipFile for invalid archives.
    """
    all_files: list[dict[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            relative_path = info.filename
            if not should_include_file(relative_path):
                continue
            if info.file_size > MAX_FILE_SIZE:  # cheap pre-check before reading
                continue
            data = zf.read(info)
            if len(data) > MAX_FILE_SIZE:
                continue
            text = data.decode("utf-8", errors="replace")
            if len(text) and len(_NON_PRINTABLE.findall(text)) / js_length(text) > 0.1:  # looks binary
                continue
            clean_path = re.sub(r"^[^/]+/", "", relative_path, count=1)  # drop the top-level folder
            if clean_path:
                all_files.append({"path": clean_path, "content": text.strip()})

    all_files.sort(key=lambda f: locale_key(f["path"]))
    all_files.sort(key=lambda f: _priority(f["path"]))  # stable: README/package.json/... first

    total_chars = 0
    included: list[dict[str, str]] = []
    skipped: list[str] = []
    for f in all_files:
        if total_chars + js_length(f["content"]) > MAX_TOTAL_CHARS:
            skipped.append(f["path"])
            continue
        included.append(f)
        total_chars += js_length(f["content"])

    return {
        "fileTree": build_file_tree([f["path"] for f in all_files]),
        "files": included,  # capped subset: used for the one-shot analysis + interview prompts
        "allFiles": all_files,  # everything: used for RAG indexing so nothing stays un-indexed
        "stats": {"total": len(all_files), "analyzed": len(included), "skipped": len(skipped), "totalChars": total_chars},
    }


def build_project_context(file_tree: str, files: list[dict[str, str]]) -> str:
    context = f"PROJECT FILE STRUCTURE:\n```\n{file_tree}\n```\n\n=== FILE CONTENTS ===\n\n"
    for f in files:
        ext = f["path"].split(".")[-1]
        context += f"--- FILE: {f['path']} ---\n```{ext}\n{f['content']}\n```\n\n"
    return context


def to_fixed(value: float, digits: int = 2) -> str:
    """JavaScript Number#toFixed semantics (round half up on the exact binary value)."""
    q = Decimal(1).scaleb(-digits)
    return str(Decimal(value).quantize(q, rounding=ROUND_HALF_UP))


async def analyze_project(file_tree: str, files: list[dict[str, str]]) -> str:
    context = build_project_context(file_tree, files)
    text = await groq_client.chat_completion(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": prompts.PROJECT_ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": prompts.render(prompts.PROJECT_ANALYSIS_PROMPT, projectContext=context)},
        ],
        temperature=0.4,
        max_tokens=1300,  # keeps input+output under the 8,000 TPM cap
    )
    return text or "Analysis failed."


async def ask_about_project_rag(relevant_chunks: list[dict[str, Any]], history: list[dict[str, str]], question: str) -> str:
    """Answer using only the retrieved chunks (RAG) instead of the whole project."""
    context = "RELEVANT CODE SECTIONS (retrieved based on your question):\n\n"
    for chunk in relevant_chunks:
        ext = chunk["filePath"].split(".")[-1]
        context += f"--- FILE: {chunk['filePath']} (relevance: {to_fixed(chunk['score'])}) ---\n```{ext}\n{chunk['content']}\n```\n\n"

    messages = [
        {"role": "system", "content": prompts.PROJECT_ANALYST_SYSTEM_PROMPT},
        {"role": "user", "content": prompts.render(prompts.RAG_USER_INTRO, context=context)},
        {
            "role": "assistant",
            "content": "Understood — I'll answer based on the relevant sections you've retrieved, and flag if I think I'm missing needed context.",
        },
        *[{"role": m["role"], "content": m["content"]} for m in history],
        {"role": "user", "content": question},
    ]
    text = await groq_client.chat_completion(model="openai/gpt-oss-120b", messages=messages, temperature=0.5, max_tokens=1500)
    return text or "Could not generate response."
