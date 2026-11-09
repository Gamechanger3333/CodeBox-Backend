"""Mock technical interview grounded in the user's own project.

Three narrow LLM jobs (keeps each prompt short/cheap on Groq's free tier):
  1. generate_interview_questions - once per project
  2. evaluate_answer              - once per answered question
  3. generate_final_report        - once, at the end
"""
from __future__ import annotations

import json
import logging
import re

from app import prompts
from app.services import groq_client
from app.services.project_analyzer import build_project_context

log = logging.getLogger("codebox.interview")

QUESTION_CATEGORIES = ["architecture", "scaling", "security", "debugging", "tradeoffs", "dependencies"]
NUM_QUESTIONS = 12
MODEL = "openai/gpt-oss-120b"

_FALLBACK_QUESTION = {
    "id": "q1",
    "category": "architecture",
    "question": "Walk me through how this project is structured, and why you organized it that way.",
}


def _strip_fences(raw: str) -> str:
    return re.sub(r"```json|```", "", raw).strip()


def parse_questions_json(raw: str) -> list[dict[str, str]]:
    """LLMs sometimes wrap JSON in fences or add a sentence - extract the array anyway,
    and fall back to one safe question rather than breaking the whole upload flow."""
    cleaned = _strip_fences(raw)
    match = re.search(r"\[[\s\S]*\]", cleaned)
    json_text = match.group(0) if match else cleaned
    try:
        parsed = json.loads(json_text)
        if not isinstance(parsed, list):
            raise ValueError("Empty or invalid array")
        valid = [q for q in parsed if isinstance(q, dict) and isinstance(q.get("question"), str) and q["question"].strip()]
        if not valid:
            raise ValueError("Empty or invalid array")
        return [
            {
                "id": f"q{i + 1}",
                "category": q.get("category") if q.get("category") in QUESTION_CATEGORIES else "architecture",
                "question": q["question"].strip(),
            }
            for i, q in enumerate(valid)
        ]
    except (ValueError, TypeError) as exc:
        log.error("Failed to parse interview questions JSON: %s", exc)
        return [dict(_FALLBACK_QUESTION)]


def parse_evaluation_json(raw: str) -> dict[str, str]:
    cleaned = _strip_fences(raw)
    match = re.search(r"\{[\s\S]*\}", cleaned)
    json_text = match.group(0) if match else cleaned
    try:
        parsed = json.loads(json_text)
        if not isinstance(parsed, dict):
            raise ValueError("not an object")
        return {
            "followUp": parsed["followUp"].strip() if isinstance(parsed.get("followUp"), str) else "Let's move to the next question.",
            "feedback": parsed["feedback"].strip() if isinstance(parsed.get("feedback"), str) else "",
            "teach": parsed["teach"].strip() if isinstance(parsed.get("teach"), str) else "",
        }
    except (ValueError, TypeError) as exc:
        log.error("Failed to parse evaluation JSON: %s", exc)
        return {
            "followUp": "Let's move to the next question.",
            "feedback": "Could not generate detailed feedback for this answer — moving on.",
            "teach": "",
        }


async def _ask(prompt: str, temperature: float, max_tokens: int) -> str | None:
    return await groq_client.chat_completion(
        model=MODEL,
        messages=[{"role": "system", "content": prompts.INTERVIEWER_SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def generate_interview_questions(file_tree: str, files: list[dict[str, str]]) -> list[dict[str, str]]:
    prompt = prompts.render(prompts.INTERVIEW_QUESTIONS_PROMPT, projectContext=build_project_context(file_tree, files))
    return parse_questions_json(await _ask(prompt, 0.6, 2000) or "[]")


async def evaluate_answer(file_tree, files, question: str, user_answer: str, transcript_so_far: list[dict]) -> dict[str, str]:
    transcript_text = (
        "\n\n".join(f"Q: {t['question']}\nA: {t['answer']}" for t in transcript_so_far)
        if transcript_so_far
        else "(this is the first question)"
    )
    prompt = prompts.render(
        prompts.INTERVIEW_EVALUATE_PROMPT,
        projectContext=build_project_context(file_tree, files),
        transcriptText=transcript_text,
        question=question,
        userAnswer=user_answer,
    )
    return parse_evaluation_json(await _ask(prompt, 0.5, 800) or "{}")


async def generate_final_report(file_tree, files, transcript: list[dict]) -> str:
    transcript_text = "\n\n".join(
        f"Q{i + 1} [{t['category']}]: {t['question']}\nAnswer: {t['answer']}\nInterviewer feedback: {t.get('feedback') or '(none)'}"
        for i, t in enumerate(transcript)
    )
    prompt = prompts.render(
        prompts.INTERVIEW_REPORT_PROMPT,
        projectContext=build_project_context(file_tree, files),
        transcriptText=transcript_text,
    )
    return await _ask(prompt, 0.4, 1800) or "Could not generate report."
