"""FR-2 and FR-3 at start-up: the server refuses to start over a broken rubric or prompt.

Entering `TestClient` as a context manager runs the app's start-up, as a real server does.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from scorer.config import PromptError, RubricError
from tests.unit.samples import ACTIVE_PROMPT_VERSION
from tests.unit.test_api import make_client


def test_fr2_the_server_starts_when_every_rubric_and_the_prompt_load(scorer_root):
    with make_client(scorer_root=scorer_root) as client:
        assert client.get("/healthz").status_code == 200


def test_fr2_the_server_refuses_to_start_over_a_broken_rubric(scorer_root):
    (scorer_root / "rubrics" / "teamwork.yaml").write_text("id: teamwork\n", encoding="utf-8")
    client: TestClient = make_client(scorer_root=scorer_root)
    with pytest.raises(RubricError), client:
        pytest.fail("the server started over a broken rubric")


def test_fr3_the_server_refuses_to_start_over_a_prompt_that_does_not_match_its_hash(scorer_root):
    prompt = scorer_root / "prompts" / "scorer" / f"{ACTIVE_PROMPT_VERSION}.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    client: TestClient = make_client(scorer_root=scorer_root)
    with pytest.raises(PromptError), client:
        pytest.fail("the server started over a changed prompt")
