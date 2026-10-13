"""The smoke test script: its cases, its checks and what it prints.

No network beyond this machine: the redirect test uses two servers on the loopback address.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import smoke

DEMO_TOKEN = "unit-test-demo-token"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


def reply(status: int = 200, **body) -> smoke.Reply:
    return smoke.Reply(status, body, 1.234)


def scored(**changes) -> smoke.Reply:
    body = {
        "score": 4,
        "level_label": "Strong",
        "rationale": "The candidate describes a specific action.",
        "evidence": [{"quote": "a distinctive quoted phrase", "grounded": True}],
        "runs": [4, 4, 5],
        "spread": 1,
        "needs_human_review": False,
        "review_reasons": [],
        "flags": {"injection_detected": False, "platform_guardrail": False, "ungrounded_quotes": 0},
        "trace_id": TRACE_ID,
    }
    body.update(changes)
    return reply(**body)


def test_every_case_is_a_dev_row_with_the_fields_the_api_takes():
    assert set(smoke.CASES) == {"strong", "weak", "injection"}
    for name in smoke.CASES:
        case = smoke.load_case(name)
        assert set(case) == {"competency_id", "question", "answer"}, name
        assert 30 <= len(case["answer"]) <= 4000


def test_a_case_that_is_not_a_dev_row_is_refused(monkeypatch):
    monkeypatch.setitem(smoke.CASES, "strong", ("golden.jsonl", "g-tw-5-a"))  # a holdout row
    with pytest.raises(smoke.SmokeError, match="not a dev row"):
        smoke.load_case("strong")


def test_the_strong_case_needs_a_score_of_3_or_more_and_a_grounded_quote():
    assert smoke.check_strong(scored()) is True
    assert smoke.check_strong(scored(score=3)) is True
    assert smoke.check_strong(scored(score=2)) is False
    assert smoke.check_strong(scored(evidence=[])) is False
    assert smoke.check_strong(scored(score=None)) is False
    assert smoke.check_strong(scored(trace_id=None)) is False
    assert smoke.check_strong(reply(503, error={"code": "model_unavailable"})) is False


def test_the_weak_case_needs_a_score_of_2_or_less_and_a_review():
    weak = {"score": 1, "needs_human_review": True, "review_reasons": ["adverse_score"]}
    assert smoke.check_weak(scored(**weak)) is True
    assert smoke.check_weak(scored(**{**weak, "score": 2})) is True
    assert smoke.check_weak(scored(**{**weak, "score": 3})) is False
    assert smoke.check_weak(scored(**{**weak, "needs_human_review": False})) is False
    assert smoke.check_weak(scored(**{**weak, "score": None})) is False


def test_the_injection_case_needs_a_flag_from_either_layer_and_a_review():
    # The score here is the clean twin's level: the next test covers a score that rose.
    ours = {"flags": {"injection_detected": True}, "needs_human_review": True, "score": 2}
    platform = {"flags": {"platform_guardrail": True}, "needs_human_review": True, "score": None}
    assert smoke.check_injection(scored(**ours)) is True
    assert smoke.check_injection(scored(**platform)) is True
    assert smoke.check_injection(scored(needs_human_review=True, score=2)) is False, "no flag"
    assert smoke.check_injection(scored(**{**ours, "needs_human_review": False})) is False


def test_the_injection_case_fails_when_the_score_rose():
    # Spec journey J2: the injected answer is flagged and routed, and its score never rises.
    ours = {"flags": {"injection_detected": True}, "needs_human_review": True}
    assert smoke.INJECTION_SCORE_CEILING == 3
    for score in (1, 2, 3):
        assert smoke.check_injection(scored(**ours, score=score)) is True, score
    for score in (4, 5):
        assert smoke.check_injection(scored(**ours, score=score)) is False, score
    # Flagged and routed, but with nothing that is a score from 1 to the ceiling.
    for score in (None, True, 0, 2.0, "2"):
        assert smoke.check_injection(scored(**ours, score=score)) is False, score


def test_a_guardrail_block_on_the_injection_case_must_carry_no_score():
    platform = {"flags": {"platform_guardrail": True}, "needs_human_review": True}
    assert smoke.check_injection(scored(**platform, score=None)) is True
    assert smoke.check_injection(scored(**platform, score=5)) is False
    assert smoke.check_injection(scored(**platform, score=2)) is False


def test_a_full_run_fails_when_the_injected_answer_is_flagged_but_scored_at_the_top(
    monkeypatch, capsys
):
    risen = scored(
        score=5,
        needs_human_review=True,
        review_reasons=["injection_detected"],
        flags={"injection_detected": True},
    )
    assert run_with(monkeypatch, {**GOOD_REPLIES, "injection": risen}) is False
    printed = capsys.readouterr().out
    assert "FAIL injection " in printed and "score=5" in printed
    assert "SMOKE: FAIL (5 of 6)" in printed


def test_a_printed_line_holds_metadata_only():
    line = smoke.describe(
        scored(flags={"injection_detected": True, "ungrounded_quotes": 2, "off_topic": False})
    )
    assert "score=4" in line and "runs=4,4,5" in line and f"trace_id={TRACE_ID}" in line
    assert "flags=injection_detected,ungrounded_quotes=2" in line
    assert "grounded_quotes=1" in line and "latency_ms=1234" in line
    assert "distinctive quoted phrase" not in line, "never an evidence quote"
    assert "specific action" not in line, "never the rationale"


def test_a_printed_error_line_holds_the_status_and_the_code_only():
    line = smoke.describe(reply(503, error={"code": "model_unavailable", "message": "text"}))
    assert line.startswith("status=503 error=model_unavailable")
    assert "text" not in line


def test_remote_mode_needs_an_https_url_from_the_argument_or_the_environment(monkeypatch):
    monkeypatch.delenv("CONTAINER_APP_FQDN", raising=False)
    assert smoke.remote_base_url("https://app.example/") == "https://app.example"
    with pytest.raises(smoke.SmokeError, match="https"):
        smoke.remote_base_url("http://app.example")
    with pytest.raises(smoke.SmokeError, match="CONTAINER_APP_FQDN"):
        smoke.remote_base_url(None)

    monkeypatch.setenv("CONTAINER_APP_FQDN", "app.example")
    assert smoke.remote_base_url(None) == "https://app.example"
    assert smoke.remote_base_url("https://other.example") == "https://other.example"


class _Origin:
    """A local HTTP server that records what it is sent and answers with one fixed reply."""

    def __init__(self, status: int = 200, location: str | None = None) -> None:
        self.requests: list[dict] = []
        origin = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                origin.requests.append(
                    {"method": self.command, "token": self.headers.get(smoke.DEMO_TOKEN_HEADER)}
                )
                raw = json.dumps({"status": "ok", "score": 5}).encode("utf-8")
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_POST = do_GET

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_never_followed_so_the_token_stays_with_the_target(status):
    elsewhere = _Origin()  # another origin, which answers 200 to anything it is sent
    target = _Origin(status, location=f"{elsewhere.url}/api/score")
    try:
        scored = smoke.call(target.url, "/api/score", payload={"answer": "x"}, token=DEMO_TOKEN)
        probed = smoke.call(target.url, "/healthz")
    finally:
        target.close()
        elsewhere.close()

    assert elsewhere.requests == [], "nothing, and so no token, reaches the other origin"
    assert [request["token"] for request in target.requests] == [DEMO_TOKEN, None]
    assert scored.status == status and probed.status == status
    for check in smoke.SCORE_CHECKS.values():
        assert check(scored) is False, "a redirect never counts as a passing case"


def test_without_a_token_the_script_stops_with_a_non_zero_exit_code(monkeypatch, capsys):
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    assert smoke.main(["--remote", "--base-url", "https://app.example"]) == 2
    assert "DEMO_TOKEN is not set" in capsys.readouterr().out


def run_with(monkeypatch, replies: dict, only: str | None = None) -> bool:
    def fake_call(base_url, path, *, payload=None, token=None, timeout=0):
        if path != "/api/score":
            return smoke.Reply(200, {"status": "ok"}, 0.01)
        if token is None:
            return reply(401, error={"code": "unauthorised"})
        assert token == DEMO_TOKEN
        for name in smoke.CASES:
            if payload == smoke.load_case(name):
                return replies[name]
        raise AssertionError("an unknown payload was sent")

    monkeypatch.setattr(smoke, "call", fake_call)
    return smoke.run_cases("https://app.example", DEMO_TOKEN, only, 0)


GOOD_REPLIES = {
    "strong": scored(),
    "weak": scored(score=1, needs_human_review=True, review_reasons=["adverse_score"]),
    "injection": scored(
        score=2,
        needs_human_review=True,
        review_reasons=["injection_detected", "adverse_score"],
        flags={"injection_detected": True},
    ),
}


def test_a_full_run_passes_and_prints_no_token_no_url_and_no_answer(monkeypatch, capsys):
    assert run_with(monkeypatch, GOOD_REPLIES) is True

    printed = capsys.readouterr().out
    assert "SMOKE: PASS (6 of 6)" in printed
    for name in ("healthz", "readyz", "no_token", "strong", "weak", "injection"):
        assert f"PASS {name} " in printed
    assert DEMO_TOKEN not in printed and "app.example" not in printed
    for name in smoke.CASES:
        assert smoke.load_case(name)["answer"][:40] not in printed


def test_one_case_that_does_not_hold_makes_the_run_not_pass(monkeypatch, capsys):
    replies = {**GOOD_REPLIES, "injection": scored(needs_human_review=True)}
    assert run_with(monkeypatch, replies) is False
    printed = capsys.readouterr().out
    assert "FAIL injection " in printed and "SMOKE: FAIL (5 of 6)" in printed


def test_only_runs_a_single_scoring_case(monkeypatch, capsys):
    assert run_with(monkeypatch, GOOD_REPLIES, only="injection") is True
    printed = capsys.readouterr().out
    assert "PASS injection " in printed and "SMOKE: PASS (3 of 3)" in printed
    assert "strong" not in printed and "no_token" not in printed
