"""RAG building blocks: chunk files -> embed -> store -> retrieve (+ LLM re-rank).

Instead of pasting the whole project into every prompt we find and send only the
chunks relevant to the question.

  1. chunking   - function/class-aware for JS/TS, 60-line windows otherwise
  2. embedding  - Ollama (local) or Gemini (hosted), vectors stored as JSONB
  3. retrieval  - cosine similarity + small keyword boost, diversity cap per file
  4. re-ranking - a small LLM re-scores the wider candidate pool (stage 2)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database import SessionLocal
from app.models import CodeChunk, IngestedFileHash, new_id, utcnow
from app.services import groq_client

try:  # numpy makes retrieval faster, but it is OPTIONAL (no wheel on some Python versions / platforms)
    import numpy as np
except ImportError:  # pure-Python fallback below
    np = None

log = logging.getLogger("codebox.rag")

# ── 1. Chunking ──────────────────────────────────────────────────────────────
CHUNK_LINES = 60  # fallback: lines per chunk for non-code / no-boundary files
CHUNK_OVERLAP = 10  # fallback: overlap between consecutive line windows
MAX_FUNCTION_CHUNK_LINES = 120  # a single function bigger than this still gets split
MIN_STANDALONE_CHUNK_LINES = 4  # blocks smaller than this are merged into the next block

JS_FAMILY_EXTENSIONS = {"js", "jsx", "ts", "tsx", "mjs", "cjs"}

# Lines that plausibly START a top-level block worth its own chunk.
# re.ASCII keeps \w identical to JavaScript's \w (ASCII only).
_BLOCK_START_PATTERNS = [
    re.compile(p, re.ASCII)
    for p in (
        r"^\s*(export\s+)?(async\s+)?function\s+\w+",
        r"^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?\(?.*\)?\s*=>",
        r"^\s*(export\s+)?class\s+\w+",
        r"^\s*exports\.\w+\s*=\s*(async\s*)?function",
        r"^\s*exports\.\w+\s*=\s*(async\s*)?\(",
        r"^\s*router\.(get|post|put|patch|delete|use)\s*\(",
    )
]


def is_block_start(line: str) -> bool:
    return any(p.match(line) for p in _BLOCK_START_PATTERNS)


def count_brace_delta(line: str) -> int:
    """Naive brace counter. Errs toward over-including rather than cutting a function in half."""
    return line.count("{") - line.count("}")


def split_into_line_windows(lines: list[str], file_path: str) -> list[dict[str, str]]:
    if len(lines) <= CHUNK_LINES:
        return [{"filePath": file_path, "content": "\n".join(lines)}]
    chunks = []
    start = 0
    while start < len(lines):
        end = min(start + CHUNK_LINES, len(lines))
        chunks.append({"filePath": file_path, "content": "\n".join(lines[start:end])})
        if end == len(lines):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def chunk_by_boundaries(content: str, file_path: str) -> list[dict[str, str]]:
    """Walk the file; when a line starts a function/class/route, capture it until its braces balance."""
    lines = content.split("\n")
    raw_blocks: list[list[str]] = []
    i = 0
    while i < len(lines):
        if is_block_start(lines[i]):
            block = [lines[i]]
            depth = count_brace_delta(lines[i])
            j = i + 1
            while depth > 0 and j < len(lines):
                block.append(lines[j])
                depth += count_brace_delta(lines[j])
                j += 1
            raw_blocks.append(block)
            i = j
        else:  # imports, comments, top-level code: keep them so nothing is silently dropped
            loose = [lines[i]]
            j = i + 1
            while j < len(lines) and not is_block_start(lines[j]):
                loose.append(lines[j])
                j += 1
            raw_blocks.append(loose)
            i = j

    merged: list[list[str]] = []
    for block in raw_blocks:  # merge tiny blocks so we never get a chunk that is just "}"
        if merged and len(merged[-1]) < MIN_STANDALONE_CHUNK_LINES:
            merged[-1].extend(block)
        else:
            merged.append(list(block))

    chunks: list[dict[str, str]] = []
    for block in merged:
        if len(block) > MAX_FUNCTION_CHUNK_LINES:
            chunks.extend(split_into_line_windows(block, file_path))
        elif block:
            chunks.append({"filePath": file_path, "content": "\n".join(block)})
    return chunks


def chunk_file(file: dict[str, str]) -> list[dict[str, str]]:
    ext = file["path"].split(".")[-1].lower()
    if ext in JS_FAMILY_EXTENSIONS:
        chunks = chunk_by_boundaries(file["content"], file["path"])
        if chunks:
            return chunks
    return split_into_line_windows(file["content"].split("\n"), file["path"])


def chunk_all_files(files: list[dict[str, str]]) -> list[dict[str, str]]:
    return [c for f in files for c in chunk_file(f)]


# ── 2. Embeddings ────────────────────────────────────────────────────────────
EMBED_MODEL = "nomic-embed-text"
GEMINI_EMBED_MODEL = "gemini-embedding-001"
GEMINI_EMBED_DIMENSIONS = 768  # same size as nomic-embed-text -> stays compatible with stored vectors


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    if get_settings().embedding_provider == "gemini":
        return await _embed_gemini(texts)
    return await _embed_ollama(texts)


async def get_embedding(text: str) -> list[float]:
    return (await get_embeddings_batch([text]))[0]


async def _embed_ollama(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    async with httpx.AsyncClient(timeout=s.embedding_timeout_seconds) as client:
        resp = await client.post(f"{s.ollama_url}/api/embed", json={"model": EMBED_MODEL, "input": texts})
    if resp.status_code >= 400:
        raise RuntimeError(f"Ollama embedding request failed: {resp.status_code}")
    return resp.json()["embeddings"]


async def _embed_gemini(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set — required when EMBEDDING_PROVIDER=gemini")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_EMBED_MODEL}:batchEmbedContents"
    body = {
        "requests": [
            {"model": f"models/{GEMINI_EMBED_MODEL}", "content": {"parts": [{"text": t}]}, "outputDimensionality": GEMINI_EMBED_DIMENSIONS}
            for t in texts
        ]
    }
    async with httpx.AsyncClient(timeout=s.embedding_timeout_seconds) as client:
        resp = await client.post(url, params={"key": s.gemini_api_key}, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"Gemini embedding request failed: {resp.status_code} {resp.text}")
    return [e["values"] for e in resp.json()["embeddings"]]


# ── 3. Similarity ────────────────────────────────────────────────────────────
def cosine_similarity(a, b) -> float:
    return semantic_scores([a], b)[0]


def semantic_scores(vectors: list[list[float]], query: list[float]) -> list[float]:
    """Cosine similarity of every vector against the query. A zero vector scores 0.0.
    Uses numpy (one vectorised pass) when installed, plain Python otherwise - same results."""
    if np is not None:
        matrix = np.asarray(vectors, dtype=float)
        q = np.asarray(query, dtype=float)
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
        with np.errstate(divide="ignore", invalid="ignore"):
            return [float(x) for x in np.where(norms > 0, (matrix @ q) / norms, 0.0)]
    q_norm = math.sqrt(sum(x * x for x in query))
    out = []
    for vec in vectors:
        denom = math.sqrt(sum(x * x for x in vec)) * q_norm
        out.append(sum(a * b for a, b in zip(vec, query)) / denom if denom else 0.0)
    return out


# ── 4. Ingestion (incremental) ───────────────────────────────────────────────
EMBED_BATCH_SIZE = 15


async def ingest_project_chunks(
    user_id: int, files: list[dict[str, str]], session_factory: async_sessionmaker[AsyncSession] = SessionLocal
) -> dict[str, int]:
    """Chunk + embed + store a user's project. Only files whose content hash changed are re-embedded."""
    session_id = str(user_id)  # userId is an Int; the sessionId column is Text

    async with session_factory() as db:
        existing = (await db.execute(select(IngestedFileHash).where(IngestedFileHash.session_id == session_id))).scalars().all()
        hash_by_path = {h.file_path: h.content_hash for h in existing}

        current_paths = {f["path"] for f in files}
        changed: list[dict[str, str]] = []
        unchanged = 0
        for f in files:
            digest = hashlib.sha256(f["content"].encode("utf-8")).hexdigest()
            if hash_by_path.get(f["path"]) == digest:
                unchanged += 1
            else:
                changed.append({**f, "_hash": digest})
        removed = [p for p in hash_by_path if p not in current_paths]
        log.info("Incremental ingestion: %d changed, %d unchanged (skipped), %d removed", len(changed), unchanged, len(removed))

        # Clean up ONLY changed + removed files - a blanket delete would also wipe the chunks we want to keep.
        to_clear = [f["path"] for f in changed] + removed
        if to_clear:
            await db.execute(delete(CodeChunk).where(CodeChunk.session_id == session_id, CodeChunk.file_path.in_(to_clear)))
            await db.execute(delete(IngestedFileHash).where(IngestedFileHash.session_id == session_id, IngestedFileHash.file_path.in_(to_clear)))
            await db.commit()

        # De-duplicate identical chunks BEFORE embedding (saves compute AND stops retrieval returning 10 copies).
        seen: dict[str, dict[str, str]] = {}
        for chunk in chunk_all_files(changed):
            seen.setdefault(hashlib.sha256(chunk["content"].strip().encode("utf-8")).hexdigest(), chunk)
        chunks = list(seen.values())

        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[start : start + EMBED_BATCH_SIZE]
            embeddings = await get_embeddings_batch([f"File: {c['filePath']}\n{c['content']}" for c in batch])
            db.add_all(
                CodeChunk(session_id=session_id, file_path=c["filePath"], content=c["content"], embedding=emb)
                for c, emb in zip(batch, embeddings)
            )
            await db.commit()  # commit per batch: never hold a transaction open across slow HTTP calls

        if changed:  # remember the new hashes so the NEXT upload can skip unchanged files
            stmt = pg_insert(IngestedFileHash).values(
                [{"id": new_id(), "sessionId": session_id, "filePath": f["path"], "contentHash": f["_hash"], "updatedAt": utcnow()} for f in changed]
            ).on_conflict_do_nothing(index_elements=["sessionId", "filePath"])
            await db.execute(stmt)
            await db.commit()

        total = (await db.execute(select(func.count()).select_from(CodeChunk).where(CodeChunk.session_id == session_id))).scalar_one()
        return {"chunkCount": total, "changedFileCount": len(changed), "skippedFileCount": unchanged}


# ── 5. Retrieval ─────────────────────────────────────────────────────────────
STOPWORDS = {"how", "does", "the", "is", "are", "a", "an", "and", "or", "to", "of", "in", "work", "works", "app", "this"}
KEYWORD_BOOST = 0.15


def extract_keywords(question: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", question.lower())
    return [w for w in re.split(r"\s+", cleaned) if len(w) > 2 and w not in STOPWORDS]


async def retrieve_relevant_chunks(
    db: AsyncSession, user_id: int, question: str, top_k: int = 6, use_reranking: bool = True, candidate_pool_size: int | None = None
) -> list[dict[str, Any]]:
    """Return the top_k chunks [{filePath, content, score}] for this user's project."""
    pool_size = candidate_pool_size if candidate_pool_size is not None else top_k * 3
    session_id = str(user_id)

    query_vec = [float(x) for x in await get_embedding(question)]
    keywords = extract_keywords(question)

    rows = (await db.execute(select(CodeChunk.file_path, CodeChunk.content, CodeChunk.embedding).where(CodeChunk.session_id == session_id))).all()
    if not rows:
        return []

    usable = [r for r in rows if isinstance(r.embedding, list) and len(r.embedding) == len(query_vec)]  # skip vectors of another size
    if not usable:
        return []
    semantic = semantic_scores([r.embedding for r in usable], query_vec)

    scored = []
    for row, sem in zip(usable, semantic):
        haystack = f"{row.file_path} {row.content}".lower()
        hits = sum(1 for kw in keywords if kw in haystack)
        boost = KEYWORD_BOOST * (hits / len(keywords)) if hits > 0 else 0.0
        scored.append({"filePath": row.file_path, "content": row.content, "score": float(sem) + boost})
    scored.sort(key=lambda r: r["score"], reverse=True)

    # Diversity cap: don't let one file's many small chunks fill every slot.
    target = pool_size if use_reranking else top_k
    max_per_file = 4 if use_reranking else 2
    counts: dict[str, int] = {}
    diverse: list[dict[str, Any]] = []
    for r in scored:
        if counts.get(r["filePath"], 0) >= max_per_file:
            continue
        counts[r["filePath"]] = counts.get(r["filePath"], 0) + 1
        diverse.append(r)
        if len(diverse) >= target:
            break

    if not use_reranking:
        return diverse
    return await rerank_chunks(question, diverse, top_k)  # stage 2: slower but smarter


# ── 6. Re-ranking ────────────────────────────────────────────────────────────
def parse_ranking_response(raw: str, candidate_count: int) -> list[dict[str, Any]]:
    """Parse the re-ranker output. The small model does NOT reliably return JSON, so:
       1. try strict JSON, 2. fall back to a regex over lines like "[3] - 8"."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    match = re.search(r"\[[\s\S]*\]", cleaned)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and all(
                isinstance(r, dict) and isinstance(r.get("index"), (int, float)) and not isinstance(r.get("index"), bool) for r in parsed
            ):
                return parsed
        except ValueError:
            pass

    results = []
    for line in cleaned.split("\n"):
        m = re.match(r"^\[(\d+)\]", line)
        if not m:
            continue
        index = int(m.group(1))
        if index >= candidate_count:  # guard against hallucinated indices
            continue
        # score = number right after a "-" (filenames have "-" followed by letters, so no false match)
        scores = re.findall(r"-\s*(\d{1,2})(?!\d)", line)
        if not scores:
            continue
        score = int(scores[-1])
        if 0 <= score <= 10:
            results.append({"index": index, "score": score})
    return results


async def rerank_chunks(question: str, candidates: list[dict[str, Any]], top_k: int = 6) -> list[dict[str, Any]]:
    if len(candidates) <= top_k:
        return candidates
    listing = "\n\n---\n\n".join(f"[{i}] File: {c['filePath']}\n{c['content'][:400]}" for i, c in enumerate(candidates))
    prompt = (
        f'Question: "{question}"\n\n'
        f"Below are {len(candidates)} code snippets (indexed [0] to [{len(candidates) - 1}]). "
        "Rate how directly relevant each one is to answering the question, on a 0-10 scale "
        "(10 = directly answers it, 0 = unrelated).\n\n"
        f"{listing}\n\n"
        'Respond with ONLY a JSON array of {"index": number, "score": number}, sorted by score descending. No other text.'
    )
    try:
        raw = await groq_client.chat_completion(
            model="openai/gpt-oss-20b",  # small/fast: this is a scoring pass, not generation
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=800,
        )
        ranked = parse_ranking_response(raw or "[]", len(candidates))
        ranked.sort(key=lambda r: r.get("score", 0), reverse=True)  # never trust the model's own ordering

        picked: list[dict[str, Any]] = []
        seen: set[int] = set()
        for r in ranked:
            idx = r["index"]
            if isinstance(idx, float) and not idx.is_integer():
                continue
            idx = int(idx)
            if 0 <= idx < len(candidates) and idx not in seen:  # also drops out-of-range / duplicate indices
                seen.add(idx)
                picked.append(candidates[idx])
        return picked[:top_k] if picked else candidates[:top_k]
    except Exception as exc:  # noqa: BLE001
        # Re-ranking is an enhancement, not a dependency: fall back to vector+keyword order.
        log.error("Re-ranking failed, falling back to vector+keyword order: %s", exc)
        return candidates[:top_k]
