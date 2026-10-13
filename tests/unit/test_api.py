"""The HTTP API through the real FastAPI app, with a fake model client (FR-1, FR-10).

Covers FR-1's 401, 429 and 503 cases, the 400 cases with no echo of the input, a
guardrail block as a 200 with a null score, readiness, the trace id and the `score` span.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.requests import Request
from starlette.testclient import TestClient

from scorer.api import MAX_BODY_BYTES, RateLimiter, client_address, create_app, token_matches
from scorer.model_client import FakeModelClient, ModelUnavailableError
from scorer.schemas import NOTICE
from tests.unit.samples import (
    EXACT_QUOTE,
    QUESTION,
    REPO_ROOT,
    TEAMWORK_ANSWER,
    good_client,
    make_settings,
)

DEMO_TOKEN = "unit-test-demo-token"
ENDPOINT = "https://foundry.invalid"
AUTH = {"X-Demo-Token": DEMO_TOKEN}
# A phrase that appears nowhere but in the request, to prove nothing echoes the input.
MARKER = "zebra-quartz-lantern-4471"

# The fixed attribute names from CLAUDE.md, written out here so that a change to the
# constant in the code cannot hide a change to the contract.
FIXED_SPAN_ATTRIBUTES = {
    "scorer.request_id",
    "scorer.answer_hash",
    "scorer.competency",
    "scorer.prompt_version",
    "scorer.prompt_sha",
    "scorer.model_deployment",
    "scorer.model_version",
    "scorer.score",
    "scorer.runs",
    "scorer.spread",
    "scorer.needs_human_review",
    "scorer.review_reasons",
    "scorer.injection_detected",
    "scorer.hidden_text_removed",
    "scorer.platform_guardrail",
    "scorer.rationale_protected_term",
    "scorer.ungrounded_quotes",
    "scorer.input_chars",
    "scorer.tokens_in",
    "scorer.tokens_out",
    "scorer.cost_estimate_gbp",
}


def body(answer: str = TEAMWORK_ANSWER, **overrides: object) -> dict:
    values: dict[str, object] = {
        "competency_id": "teamwork",
        "question": QUESTION,
        "answer": answer,
    }
    values.update(overrides)
    return values


def make_client(model_client=None, *, rate_limiter=None, exporter=None, **overrides) -> TestClient:
    values = {"demo_token": DEMO_TOKEN, "foundry_endpoint": ENDPOINT}
    values.update(overrides)
    provider = None
    if exporter is not None:
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(
        make_settings(**values),
        model_client if model_client is not None else good_client(),
        tracer_provider=provider,
        rate_limiter=rate_limiter,
    )
    return TestClient(app)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message"}
    assert payload["error"]["code"] == code


# --- 200 --------------------------------------------------------------------------------


def test_fr1_a_valid_request_returns_the_score_with_a_trace_id_and_the_notice():
    response = make_client().post("/api/score", json=body(), headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] == 4 and payload["level_label"]
    assert payload["runs"] == [4, 4, 4] and payload["spread"] == 0
    assert payload["evidence"] == [{"quote": EXACT_QUOTE, "grounded": True}]
    assert payload["notice"] == NOTICE
    assert payload["prompt_version"] == "v1" and payload["model_deployment"] == "scorer-mini"
    trace_id = payload["trace_id"]
    assert len(trace_id) == 32 and int(trace_id, 16) != 0
    assert response.headers["cache-control"] == "no-store"


def test_fr1_the_trace_id_in_the_response_is_the_trace_id_of_the_score_span():
    exporter = InMemorySpanExporter()
    response = make_client(exporter=exporter).post("/api/score", json=body(), headers=AUTH)

    (span,) = exporter.get_finished_spans()
    assert span.name == "score"
    assert response.json()["trace_id"] == format(span.context.trace_id, "032x")


def test_fr1_candidate_ref_is_accepted_and_never_returned():
    response = make_client().post("/api/score", json=body(candidate_ref=MARKER), headers=AUTH)
    assert response.status_code == 200
    assert MARKER not in response.text


# --- 401 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Demo-Token": ""},
        {"X-Demo-Token": "wrong-token"},
        {"X-Demo-Token": DEMO_TOKEN + "x"},
        {"X-Demo-Token": DEMO_TOKEN[:-1]},
        {"Authorization": f"Bearer {DEMO_TOKEN}"},
    ],
)
def test_fr1_a_missing_or_wrong_demo_token_is_401_and_the_model_is_not_called(headers):
    model = good_client()
    response = make_client(model).post("/api/score", json=body(), headers=headers)

    assert_error(response, 401, "unauthorised")
    assert model.calls == []


def test_fr1_no_request_is_let_in_when_the_server_has_no_demo_token():
    model = good_client()
    client = make_client(model, demo_token=None)

    assert_error(client.post("/api/score", json=body(), headers=AUTH), 401, "unauthorised")
    assert_error(client.post("/api/score", json=body()), 401, "unauthorised")
    assert model.calls == []


def test_the_token_comparison_is_constant_time_and_strict(monkeypatch):
    seen = []

    def compare(left, right):
        seen.append((left, right))
        return left == right

    monkeypatch.setattr("scorer.api.hmac.compare_digest", compare)
    assert token_matches(DEMO_TOKEN, DEMO_TOKEN) is True
    assert token_matches("other", DEMO_TOKEN) is False
    assert len(seen) == 2, "every non-empty comparison goes through hmac.compare_digest"
    assert token_matches(None, DEMO_TOKEN) is False
    assert token_matches(DEMO_TOKEN, None) is False
    assert token_matches("", "") is False


# --- 429 --------------------------------------------------------------------------------


def test_fr1_the_eleventh_request_in_a_minute_from_one_address_is_429():
    model = good_client()
    client = make_client(model)

    for _ in range(10):
        assert client.post("/api/score", json=body(), headers=AUTH).status_code == 200
    response = client.post("/api/score", json=body(), headers=AUTH)

    assert_error(response, 429, "rate_limited")
    assert response.headers["retry-after"] == "60"
    assert len(model.calls) == 30, "the refused request made no model call"


def test_fr1_the_rate_limit_is_per_address_from_the_last_forwarded_hop():
    # The ingress appends the address it saw as the last value. Everything before it is
    # whatever the caller sent, so it is not part of the key.
    client = make_client()
    first = {**AUTH, "X-Forwarded-For": "10.0.0.1, 203.0.113.7"}
    same = {**AUTH, "X-Forwarded-For": "10.9.9.9, 203.0.113.7"}
    other = {**AUTH, "X-Forwarded-For": "10.0.0.1, 203.0.113.8"}

    for _ in range(10):
        assert client.post("/api/score", json=body(), headers=first).status_code == 200
    assert client.post("/api/score", json=body(), headers=same).status_code == 429
    assert client.post("/api/score", json=body(), headers=other).status_code == 200


def test_fr1_a_spoofed_first_hop_does_not_change_the_rate_limit_key():
    model = good_client()
    client = make_client(model)
    statuses = [
        client.post(
            "/api/score",
            json=body(),
            headers={**AUTH, "X-Forwarded-For": f"198.51.100.{number}, 203.0.113.7"},
        ).status_code
        for number in range(40)
    ]
    assert statuses == [200] * 10 + [429] * 30
    assert len(model.calls) == 30, "only the first ten requests reached the model"


def test_fr1_a_caller_cannot_spend_another_address_by_naming_it_in_the_header():
    client = make_client()
    victim = "203.0.113.50"
    # The attacker, seen by the ingress at 203.0.113.99, names the victim's address.
    attack = {"X-Forwarded-For": f"{victim}, 203.0.113.99"}
    for _ in range(10):
        assert client.post("/api/score", json=body(), headers=attack).status_code == 401
    assert client.post("/api/score", json=body(), headers=attack).status_code == 429

    # The victim's own request, with the address the ingress appended, is not limited.
    own = {**AUTH, "X-Forwarded-For": victim}
    assert client.post("/api/score", json=body(), headers=own).status_code == 200


def test_the_rate_limit_key_is_the_last_hop_or_else_the_socket_address():
    def address(headers: list[tuple[bytes, bytes]], peer=("192.0.2.9", 5000)) -> str:
        scope = {"type": "http", "headers": headers, "client": peer}
        return client_address(Request(scope))

    forwarded = b"x-forwarded-for"
    assert address([]) == "192.0.2.9"
    assert address([(forwarded, b"203.0.113.7")]) == "203.0.113.7"
    assert address([(forwarded, b"1.1.1.1, 2.2.2.2 , 203.0.113.7 ")]) == "203.0.113.7"
    # A second header line sent by the caller cannot hide the one the ingress wrote last.
    assert address([(forwarded, b"1.1.1.1"), (forwarded, b"2.2.2.2, 203.0.113.7")]) == (
        "203.0.113.7"
    )
    # An empty last value is not an address: fall back to the socket.
    assert address([(forwarded, b"1.1.1.1, ")]) == "192.0.2.9"
    assert address([(forwarded, b"")], peer=None) == "unknown"
    assert len(address([(forwarded, b"1.1.1.1, " + b"9" * 500)])) == 64


def test_fr1_requests_without_a_token_count_towards_the_limit():
    client = make_client()
    for _ in range(10):
        assert client.post("/api/score", json=body()).status_code == 401
    assert client.post("/api/score", json=body(), headers=AUTH).status_code == 429


def test_the_rate_limit_window_slides():
    now = [1000.0]
    limiter = RateLimiter(limit=2, window_seconds=60.0, clock=lambda: now[0])

    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b"), "another key has its own count"
    now[0] += 59.0
    assert not limiter.allow("a")
    now[0] += 1.5
    assert limiter.allow("a"), "the first two requests have left the window"


def test_the_rate_limiter_does_not_grow_without_limit():
    now = [0.0]
    limiter = RateLimiter(limit=1, window_seconds=60.0, clock=lambda: now[0], max_keys=3)
    for key in ("a", "b", "c"):
        assert limiter.allow(key)
    now[0] += 61.0
    assert limiter.allow("d")
    assert len(limiter._hits) == 1, "idle keys were dropped"


def test_a_full_table_does_not_reset_a_key_that_is_being_limited():
    now = [0.0]
    limiter = RateLimiter(limit=2, window_seconds=60.0, clock=lambda: now[0], max_keys=3)
    assert limiter.allow("limited") and limiter.allow("limited")
    assert not limiter.allow("limited")

    # A flood of new keys, all inside the window, fills the table many times over.
    for number in range(50):
        now[0] += 0.1
        assert limiter.allow(f"flood-{number}")
        assert len(limiter._hits) <= 3, "the table never grows past its bound"
        assert not limiter.allow("limited"), "the flood did not clear the counter"

    now[0] += 61.0
    assert limiter.allow("limited"), "the limit lifts only when the window has passed"


def test_a_full_table_drops_the_quietest_keys_in_batches_and_stays_bounded():
    now = [0.0]
    limiter = RateLimiter(limit=3, window_seconds=60.0, clock=lambda: now[0], max_keys=20)
    for key in ("busy-a", "busy-b"):
        assert all(limiter.allow(key) for _ in range(3))
    for number in range(200):
        now[0] += 0.01
        limiter.allow(f"once-{number}")
        assert len(limiter._hits) <= 20
    assert not limiter.allow("busy-a") and not limiter.allow("busy-b")
    assert all(len(hits) <= 3 for hits in limiter._hits.values())


def test_health_and_the_page_are_not_rate_limited():
    client = make_client()
    for _ in range(15):
        assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200


# --- 503 --------------------------------------------------------------------------------


def test_fr1_a_model_failure_is_503_with_no_score_of_any_kind():
    client = make_client(FakeModelClient(ModelUnavailableError("synthetic outage")))
    response = client.post("/api/score", json=body(), headers=AUTH)

    assert_error(response, 503, "model_unavailable")
    assert "score" not in response.json()
    assert "level_label" not in response.text and "runs" not in response.text


def test_fr1_one_failed_run_of_three_is_503_and_never_a_partial_score():
    script = [
        FakeModelClient.output(4),
        ModelUnavailableError("one run down"),
        FakeModelClient.output(4),
    ]
    response = make_client(FakeModelClient(script)).post("/api/score", json=body(), headers=AUTH)
    assert_error(response, 503, "model_unavailable")


def test_fr1_output_that_is_not_valid_is_503():
    bad = {"score": 9, "rationale": "x", "evidence": [], "off_topic": False}
    response = make_client(FakeModelClient(bad)).post("/api/score", json=body(), headers=AUTH)
    assert_error(response, 503, "model_unavailable")


def test_fr1_no_model_client_is_503_never_a_default_score():
    app = create_app(make_settings(demo_token=DEMO_TOKEN, foundry_endpoint=None), None)
    response = TestClient(app).post("/api/score", json=body(), headers=AUTH)
    assert_error(response, 503, "model_unavailable")


def test_fr1_an_exception_inside_the_model_client_is_503_and_its_text_goes_nowhere(caplog):
    def explode(_messages):
        raise RuntimeError(MARKER)

    caplog.set_level(logging.DEBUG)
    exporter = InMemorySpanExporter()
    client = make_client(FakeModelClient(explode), exporter=exporter)
    response = client.post("/api/score", json=body(), headers=AUTH)

    assert_error(response, 503, "model_unavailable")
    assert MARKER not in response.text
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert MARKER not in (span.status.description or "")
    assert not span.events, "no exception event, so no error text on the span"
    assert MARKER not in "\n".join(record.getMessage() for record in caplog.records)


def test_an_unexpected_error_is_500_with_no_detail_and_no_score(scorer_root, caplog):
    # This root has rubrics and prompts but no price file, so the cost estimate cannot be made.
    caplog.set_level(logging.DEBUG)
    exporter = InMemorySpanExporter()
    client = make_client(exporter=exporter, scorer_root=scorer_root)
    response = client.post("/api/score", json=body(), headers=AUTH)

    assert_error(response, 500, "internal_error")
    assert "score" not in response.json()
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "internal_error"
    assert not span.events
    assert str(scorer_root) not in "\n".join(record.getMessage() for record in caplog.records)


# --- 400 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_body", "code"),
    [
        (body(competency_id="leadership"), "unknown_competency"),
        (body(competency_id="../rubrics/teamwork"), "unknown_competency"),
        (body(answer="Too short " + MARKER[:5]), "answer_too_short"),
        (body(answer=(MARKER + " ") * 200), "answer_too_long"),
        (
            body(answer="Reach me at someone@example.org or 01632 960123, see https://example.com"),
            "answer_empty_after_redaction",
        ),
    ],
)
def test_fr1_a_request_that_cannot_be_scored_is_400_with_its_code(request_body, code):
    model = good_client()
    response = make_client(model).post("/api/score", json=request_body, headers=AUTH)

    assert_error(response, 400, code)
    assert MARKER not in response.text and "example.org" not in response.text
    assert model.calls == []


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"{not json " + MARKER.encode(),
        b'"' + MARKER.encode() + b'"',
        b"[1, 2, 3]",
        b"\xff\xfe" + MARKER.encode(),
        json.dumps(body(name=MARKER)).encode(),
        json.dumps(body(gender=MARKER)).encode(),
        json.dumps(body(rubric={"levels": [MARKER]})).encode(),
        json.dumps({"competency_id": "teamwork", "question": MARKER}).encode(),
        json.dumps(body(answer=12345, question=MARKER)).encode(),
        json.dumps(body(answer=None, question=MARKER)).encode(),
        json.dumps(body(answer=[MARKER])).encode(),
    ],
)
def test_fr1_a_malformed_body_or_an_unknown_field_is_a_generic_400_with_no_echo(content):
    model = good_client()
    response = make_client(model).post(
        "/api/score", content=content, headers={**AUTH, "Content-Type": "application/json"}
    )

    assert_error(response, 400, "invalid_request")
    assert response.json()["error"]["message"] == "The request body is not valid."
    assert MARKER not in response.text
    assert model.calls == []


def test_fr1_a_question_over_the_limit_is_400_and_the_model_is_not_called():
    model = good_client()
    question = (MARKER + " ") * 2000  # about 50,000 characters, inside the body limit
    response = make_client(model).post("/api/score", json=body(question=question), headers=AUTH)

    assert_error(response, 400, "question_too_long")
    assert MARKER not in response.text
    assert model.calls == []


def test_fr1_an_oversized_body_is_a_generic_400():
    content = json.dumps(body(question=MARKER * (MAX_BODY_BYTES // len(MARKER) + 1))).encode()
    response = make_client().post(
        "/api/score", content=content, headers={**AUTH, "Content-Type": "application/json"}
    )
    assert_error(response, 400, "invalid_request")
    assert MARKER not in response.text


def test_the_rejected_request_leaves_no_candidate_text_in_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    client = make_client()
    client.post("/api/score", json=body(name=MARKER), headers=AUTH)
    client.post("/api/score", json=body(answer=(MARKER + " ") * 200), headers=AUTH)
    client.post("/api/score", json=body(answer=TEAMWORK_ANSWER + " " + MARKER), headers=AUTH)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert MARKER not in logged
    assert TEAMWORK_ANSWER[:40] not in logged and QUESTION not in logged


# --- Guardrail block --------------------------------------------------------------------


def test_fr1_a_guardrail_block_is_200_with_a_null_score_and_is_routed():
    exporter = InMemorySpanExporter()
    client = make_client(FakeModelClient(FakeModelClient.blocked()), exporter=exporter)
    response = client.post("/api/score", json=body(), headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] is None and payload["level_label"] is None
    assert payload["runs"] == [] and payload["spread"] is None and payload["evidence"] == []
    assert payload["flags"]["platform_guardrail"] is True
    assert payload["needs_human_review"] is True
    assert "platform_guardrail" in payload["review_reasons"]
    assert payload["notice"] == NOTICE and len(payload["trace_id"]) == 32

    (span,) = exporter.get_finished_spans()
    assert span.attributes["scorer.platform_guardrail"] is True
    assert span.attributes["scorer.needs_human_review"] is True
    assert set(span.attributes) == FIXED_SPAN_ATTRIBUTES - {"scorer.score", "scorer.spread"}
    assert span.status.status_code is not StatusCode.ERROR


def test_fr1_one_blocked_run_of_three_is_still_a_routed_200():
    script = [FakeModelClient.output(4), FakeModelClient.blocked(), FakeModelClient.output(4)]
    response = make_client(FakeModelClient(script)).post("/api/score", json=body(), headers=AUTH)
    assert response.status_code == 200
    assert response.json()["score"] is None


# --- The score span ---------------------------------------------------------------------


def test_the_score_span_carries_exactly_the_fixed_attribute_names():
    exporter = InMemorySpanExporter()
    model = FakeModelClient(
        FakeModelClient.output(
            4,
            evidence=[EXACT_QUOTE],
            tokens_in=1000,
            tokens_out=100,
            model_version="2026-03-17",
        )
    )
    response = make_client(model, exporter=exporter).post("/api/score", json=body(), headers=AUTH)
    payload = response.json()

    (span,) = exporter.get_finished_spans()
    attributes = dict(span.attributes)
    assert span.name == "score"
    assert set(attributes) == FIXED_SPAN_ATTRIBUTES
    assert attributes["scorer.request_id"] == payload["request_id"]
    assert attributes["scorer.competency"] == "teamwork"
    assert attributes["scorer.prompt_version"] == "v1"
    assert len(attributes["scorer.prompt_sha"]) == 64
    assert len(attributes["scorer.answer_hash"]) == 64
    assert attributes["scorer.model_deployment"] == "scorer-mini"
    assert attributes["scorer.model_version"] == "2026-03-17"
    assert attributes["scorer.score"] == 4
    assert attributes["scorer.runs"] == "4,4,4"
    assert attributes["scorer.spread"] == 0
    assert attributes["scorer.needs_human_review"] is False
    assert attributes["scorer.review_reasons"] == ""
    assert attributes["scorer.injection_detected"] is False
    assert attributes["scorer.hidden_text_removed"] is False
    assert attributes["scorer.platform_guardrail"] is False
    assert attributes["scorer.rationale_protected_term"] is False
    assert attributes["scorer.ungrounded_quotes"] == 0
    assert attributes["scorer.input_chars"] == len(TEAMWORK_ANSWER)
    assert attributes["scorer.tokens_in"] == 3000
    assert attributes["scorer.tokens_out"] == 300
    # 3000 input tokens and 300 output tokens at the prices in config/prices.yaml.
    assert attributes["scorer.cost_estimate_gbp"] == pytest.approx(0.002717, abs=1e-6)


def test_no_span_attribute_holds_candidate_text():
    exporter = InMemorySpanExporter()
    rationale = "The candidate asked both colleagues for their view before proposing a plan."
    model = FakeModelClient(FakeModelClient.output(2, rationale=rationale, evidence=[EXACT_QUOTE]))
    answer = TEAMWORK_ANSWER + " " + MARKER
    question = QUESTION + " " + MARKER
    response = make_client(model, exporter=exporter).post(
        "/api/score",
        json=body(answer=answer, question=question, candidate_ref="ref-" + MARKER),
        headers=AUTH,
    )
    assert response.status_code == 200

    (span,) = exporter.get_finished_spans()
    assert span.attributes["scorer.review_reasons"] == "adverse_score"
    for name, value in span.attributes.items():
        text = str(value)
        assert MARKER not in text, name
        assert EXACT_QUOTE not in text and rationale not in text, name
        assert answer[:30] not in text and QUESTION not in text, name
        assert len(text) <= 80, f"{name} is longer than any id, hash or flag"
    assert not span.events and not span.links


def test_a_request_that_is_not_scored_leaves_a_span_with_no_attributes():
    exporter = InMemorySpanExporter()
    client = make_client(FakeModelClient(ModelUnavailableError("down")), exporter=exporter)
    client.post("/api/score", json=body(), headers=AUTH)
    client.post("/api/score", json=body(competency_id="leadership"), headers=AUTH)

    unavailable, rejected = exporter.get_finished_spans()
    assert not unavailable.attributes and not rejected.attributes
    assert unavailable.status.status_code is StatusCode.ERROR
    assert unavailable.status.description == "model_unavailable"
    assert rejected.status.status_code is not StatusCode.ERROR


def test_a_request_stopped_before_the_pipeline_makes_no_span():
    exporter = InMemorySpanExporter()
    client = make_client(exporter=exporter)
    client.post("/api/score", json=body())
    client.post("/api/score", content=b"{", headers=AUTH)
    assert exporter.get_finished_spans() == ()


# --- Health and readiness ---------------------------------------------------------------


def test_fr10_healthz_says_the_process_is_up_and_needs_no_token():
    response = make_client().get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_fr10_readyz_is_200_when_everything_loads_and_makes_no_model_call():
    model = good_client()
    response = make_client(model).get("/readyz")
    assert response.status_code == 200 and response.json() == {"status": "ready"}
    assert model.calls == []


@pytest.mark.parametrize(
    ("setting", "name"),
    [
        ("foundry_endpoint", "FOUNDRY_ENDPOINT"),
        ("demo_token", "DEMO_TOKEN"),
        ("answer_hash_salt", "ANSWER_HASH_SALT"),
    ],
)
def test_fr10_readyz_is_503_when_a_required_setting_is_missing(setting, name):
    response = make_client(**{setting: None}).get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "problems": [name]}


def test_fr10_readyz_is_503_when_a_rubric_the_prompt_or_the_prices_do_not_load(scorer_root):
    client = make_client(scorer_root=scorer_root)
    assert client.get("/readyz").json()["problems"] == ["prices"]

    (scorer_root / "rubrics" / "teamwork.yaml").write_text("id: teamwork\n", encoding="utf-8")
    prompt = scorer_root / "prompts" / "scorer" / "v1.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")

    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["problems"] == ["rubrics", "prompt", "prices"]


def test_readyz_never_shows_a_setting_value():
    response = make_client(answer_hash_salt=None).get("/readyz")
    assert DEMO_TOKEN not in response.text and ENDPOINT not in response.text


def test_the_api_has_no_generated_docs_routes():
    client = make_client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


# --- Importing the module ---------------------------------------------------------------

# Run in a child process, so that the import is a first import. The telemetry set-up is
# replaced by a recorder before `scorer.api` is loaded, so nothing can reach an exporter
# even if the behaviour under test is ever lost.
IMPORT_PROBE = """
import scorer.telemetry as telemetry

calls = []
telemetry.configure_telemetry = lambda settings: calls.append("configure") or False

import scorer.api as api

assert calls == [], "importing scorer.api configured telemetry"
assert "app" not in vars(api), "importing scorer.api built the app"
assert telemetry.telemetry_configured() is False

app = api.app  # what the server does when it starts
assert calls == ["configure"], "asking for the app did not configure telemetry"
assert api.app is app, "the app is built once"
assert app.state.settings.demo_token == "probe-token"
print("import-probe-ok")
"""


def test_importing_the_api_module_builds_and_configures_nothing():
    environment = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "src"),
        "SCORER_ROOT": str(REPO_ROOT),
        # A shell that holds a connection string, as a developer's might.
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "synthetic-connection-value",
        "DEMO_TOKEN": "probe-token",
        "FOUNDRY_ENDPOINT": "",
    }
    done = subprocess.run(
        [sys.executable, "-c", IMPORT_PROBE],
        capture_output=True,
        text=True,
        env=environment,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert "import-probe-ok" in done.stdout


def test_the_module_has_no_other_lazy_attribute():
    import scorer.api as api

    with pytest.raises(AttributeError):
        _ = api.application
