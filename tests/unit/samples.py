"""Synthetic sample text and small helpers shared by the unit tests. No real data."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from scorer.config import Settings
from scorer.model_client import FakeModelClient
from scorer.pipeline import ScoreOutcome, score_answer
from scorer.schemas import ScoreRequest

REPO_ROOT = Path(__file__).resolve().parents[2]


def active_prompt_version(root: Path = REPO_ROOT) -> str:
    """The prompt version the committed registry names as active.

    Read straight from the registry file, not through the scorer, so that a test which
    expects "the active prompt version" compares against the file and not against the code
    under test.
    """
    path = root / "prompts" / "scorer" / "registry.yaml"
    active = yaml.safe_load(path.read_text(encoding="utf-8"))["active"]
    assert isinstance(active, str) and active, "the registry names an active prompt version"
    return active


ACTIVE_PROMPT_VERSION = active_prompt_version()

QUESTION = "Tell me about a time you resolved a conflict in a team."

TEAMWORK_ANSWER = (
    "Last year our support team had to move to a new ticketing tool in six weeks. "
    "Two colleagues disagreed about the order of work: one wanted to migrate old tickets "
    "first, the other wanted to train people first. "
    "I asked each of them to explain their concern before I suggested anything, and I "
    "changed my own plan after hearing them. "
    "We agreed to train one small group first and migrate their tickets as a pilot. "
    "I shared a weekly progress note with the whole team and offered to cover a shift so a "
    "colleague could attend training. "
    "We finished four days early and the team kept the weekly note afterwards."
)

EXACT_QUOTE = "I asked each of them to explain their concern before I suggested anything"
SECOND_QUOTE = "We finished four days early"
PARAPHRASED_QUOTE = "The candidate consulted both colleagues before proposing a way forward"
INVENTED_QUOTE = "I designed a new training programme for forty people in the region"

# Ordinary answers with phrases that look a little like injection text, but are not.
ORDINARY_ANSWERS = (
    TEAMWORK_ANSWER,
    "Our reporting job failed every Monday. I checked the logs and switched the service into "
    "debug mode to gather information. I ruled out the network because the errors appeared on "
    "one server only. The cause was a full disk after a system update. I compared two options, "
    "a bigger disk or a clean-up job, and chose the clean-up job because it carried less risk "
    "for other teams. I checked the next three runs and added an alert so it could not recur.",
    "I had to act as a mediator between two colleagues who disagreed about priorities. I asked "
    "each of them what they needed, and we agreed to rank the tasks together. My manager told "
    "me to ignore the noise and focus on the customer. Our satisfaction score rose from 3.2 to "
    "4.5 over the quarter and the team kept the weekly review.",
    "When evaluating this option I listed the criteria first: cost, risk and the effect on the "
    "support team. The new process meets all the acceptance criteria we agreed. I gave the team "
    "five minutes at the start of each meeting to raise concerns, and I asked the system "
    "administrator to give me the highest level of access for one day so I could test the fix.",
    "A colleague was new, so I offered to pair up for a week. We did a role play of a difficult "
    "customer call for practice. I said, you should give the customer time to explain before "
    "you answer. The next call went well and the customer rated it five stars. The team now "
    "uses the same exercise for every new starter.",
    "We agreed new guidelines: every request goes through one shared board. I set aside my own "
    "preference after listening to the team, and I marked each task as done only when the "
    "reviewer confirmed it. I followed the instructions in the supplier manual to restart the "
    "system, then recorded a severity level of three on the incident form.",
)


def make_settings(root: Path = REPO_ROOT, **overrides: object) -> Settings:
    """Settings that never read the developer's environment."""
    values: dict[str, object] = {
        "scorer_root": root,
        "scorer_prompt_version": None,
        "model_deployment": "scorer-mini",
        "model_version": "2026-03-17",
        "foundry_endpoint": None,
        "answer_hash_salt": "unit-test-salt",
        "demo_token": None,
        "applicationinsights_connection_string": None,
    }
    values.update(overrides)
    return Settings(**values)


def make_request(answer: str = TEAMWORK_ANSWER, **overrides: object) -> ScoreRequest:
    values: dict[str, object] = {
        "competency_id": "teamwork",
        "question": QUESTION,
        "answer": answer,
    }
    values.update(overrides)
    return ScoreRequest(**values)


def good_client(score: int = 4, **kwargs: object) -> FakeModelClient:
    """A client whose three runs agree, with one grounded quote."""
    kwargs.setdefault("evidence", [EXACT_QUOTE])
    return FakeModelClient(FakeModelClient.output(score, **kwargs))


def run_score(
    request: ScoreRequest | None = None,
    client: FakeModelClient | None = None,
    settings: Settings | None = None,
) -> ScoreOutcome:
    return asyncio.run(
        score_answer(
            request or make_request(),
            client=client or good_client(),
            settings=settings or make_settings(),
        )
    )


def user_message(client: FakeModelClient, call: int = 0) -> str:
    return next(m["content"] for m in client.calls[call] if m["role"] == "user")


def system_message(client: FakeModelClient, call: int = 0) -> str:
    return next(m["content"] for m in client.calls[call] if m["role"] == "system")


def payload_text(client: FakeModelClient) -> str:
    """Everything sent to the model across all calls, as one string."""
    return "\n".join(str(message) for call in client.calls for message in call)
