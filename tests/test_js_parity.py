"""Parity with the ORIGINAL Node.js implementation.

tests/fixtures/js_parity.json holds outputs recorded by running the original JavaScript
(chunker, ranking parser, file filter, question/evaluation parsers, ZIP extraction) on
the same inputs. The Python port must produce identical results.
(Regenerate with the original repo: see README "Parity fixtures".)
"""
import json
from pathlib import Path

import pytest

from app.services import interview_analyzer, project_analyzer, rag_engine

FX = json.loads((Path(__file__).parent / "fixtures" / "js_parity.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FX["chunk"], ids=[c["path"] for c in FX["chunk"]])
def test_chunking_matches_node(case):
    got = rag_engine.chunk_file({"path": case["path"], "content": case["content"]})
    assert got == case["chunks"]


@pytest.mark.parametrize("case", FX["rank"], ids=[f"rank{i}" for i in range(len(FX["rank"]))])
def test_ranking_parser_matches_node(case):
    assert rag_engine.parse_ranking_response(case["raw"], case["count"]) == case["result"]


@pytest.mark.parametrize("case", FX["include"], ids=[c["path"] for c in FX["include"]])
def test_file_filter_matches_node(case):
    assert project_analyzer.should_include_file(case["path"]) is case["result"]


@pytest.mark.parametrize("case", FX["evaluation"], ids=[f"eval{i}" for i in range(len(FX["evaluation"]))])
def test_evaluation_parser_matches_node(case):
    assert interview_analyzer.parse_evaluation_json(case["raw"]) == case["result"]


@pytest.mark.parametrize("case", FX["questions"], ids=[f"q{i}" for i in range(len(FX["questions"]))])
def test_question_parser_matches_node(case):
    got = interview_analyzer.parse_questions_json(case["raw"])
    if case["result"] == []:
        # Deliberate improvement: Node returned an EMPTY interview (0 questions) when the model
        # produced objects without usable questions; Python falls back to the safe default question.
        assert got == [interview_analyzer._FALLBACK_QUESTION]
    else:
        assert got == case["result"]


def test_zip_extraction_matches_node():
    zip_bytes = (Path(__file__).parent / "fixtures" / "sample_project.zip").read_bytes()
    got = project_analyzer.extract_project_files(zip_bytes)
    exp = FX["sample"]
    assert got["fileTree"] == exp["fileTree"]
    assert got["stats"] == exp["stats"]
    assert [f["path"] for f in got["allFiles"]] == exp["allPaths"]
    assert got["files"] == exp["files"]
