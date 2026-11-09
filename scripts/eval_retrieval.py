"""Measure retrieval quality: for questions with KNOWN answers, does retrieval find the right file?

    python -m scripts.eval_retrieval            # uses USER_ID below
    USER_ID=3 python -m scripts.eval_retrieval

Run it AFTER uploading a project through the app (the CodeChunk table must contain data for that
user) and after editing TEST_CASES to match YOUR project. This is how you go from "it seems to
work" to "I measured that it works 5/6 times".
"""
import asyncio
import os
import sys

from app.database import SessionLocal, engine
from app.services.rag_engine import retrieve_relevant_chunks

USER_ID = int(os.environ.get("USER_ID", "1"))  # your test user's id

# The "answer key": which file SHOULD show up for each question (decide it by reading the code).
TEST_CASES = [
    {"question": "how does user login and authentication work?", "expected": "authMiddleware"},
    {"question": "how is the database connection configured?", "expected": "database"},
    {"question": "how are courses fetched or managed?", "expected": "course"},
    {"question": "how is an assignment created?", "expected": "assignment"},
    {"question": "how are teacher profiles handled?", "expected": "teacherProfile"},
    {"question": "how does the app handle payments or subscriptions?", "expected": "stripe"},
]


async def evaluate() -> None:
    print(f"Running {len(TEST_CASES)} retrieval test cases...\n")
    passed = 0
    async with SessionLocal() as db:
        for test in TEST_CASES:
            results = await retrieve_relevant_chunks(db, USER_ID, test["question"], top_k=5)
            found = any(test["expected"].lower() in r["filePath"].lower() for r in results)
            passed += found
            print(f"{'✅ PASS' if found else '❌ FAIL'} — \"{test['question']}\"")
            print(f"   expected filePath to include: \"{test['expected']}\"")
            top = results[0] if results else None
            print(f"   top result: {top['filePath'] if top else 'none'} (score: {top['score']:.3f})" if top else "   top result: none (score: n/a)")
            print(f"   all retrieved: {', '.join(r['filePath'] for r in results)}\n")
    print(f"\n=== Result: {passed}/{len(TEST_CASES)} passed ({passed / len(TEST_CASES) * 100:.1f}% accuracy) ===")
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(evaluate())
    except Exception as exc:  # noqa: BLE001
        print("Evaluation failed:", exc)
        sys.exit(1)
