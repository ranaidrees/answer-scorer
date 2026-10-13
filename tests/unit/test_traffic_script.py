"""The traffic script, run against a stub server on this machine. No model, no cloud."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import traffic

DEMO_TOKEN = "unit-test-demo-token"
DATASET_FILES = ("golden.jsonl", "fairness_pairs.jsonl", "injection.jsonl")
ANSWER_KEYS = ("answer", "answer_a", "answer_b")


def all_rows() -> list[dict]:
    rows = []
    for name in DATASET_FILES:
        with (traffic.DATASETS / name).open(encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def answers(split: str) -> set[str]:
    return {
        row[key] for row in all_rows() if row["split"] == split for key in ANSWER_KEYS if key in row
    }


def scored_body(payload: dict) -> dict:
    """A reply shaped like the service's, with the answer echoed where the service has text."""
    return {
        "request_id": "stub",
        "competency_id": payload["competency_id"],
        "score": 2,
        "level_label": "Developing",
        "rationale": f"The answer says: {payload['answer']}",
        "evidence": [{"quote": payload["answer"][:60], "grounded": True}],
        "runs": [2, 2, 3],
        "spread": 1,
        "needs_human_review": True,
        "review_reasons": ["injection_detected", "adverse_score"],
        "flags": {"injection_detected": True, "platform_guardrail": False, "ungrounded_quotes": 2},
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
    }


class Stub:
    """A local HTTP server that records every request and answers from a script."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.respond: Callable[[int, dict], tuple[int, dict, dict]] = lambda number, payload: (
            200,
            scored_body(payload),
            {},
        )
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                stub.requests.append(
                    {
                        "path": self.path,
                        "token": self.headers.get("X-Demo-Token"),
                        "payload": payload,
                    }
                )
                status, body, headers = stub.respond(len(stub.requests), payload)
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def statuses(self, *statuses: int, headers: dict | None = None) -> None:
        """Answer the first requests with these statuses, then 200 for the rest."""

        def respond(number: int, payload: dict) -> tuple[int, dict, dict]:
            status = statuses[number - 1] if number <= len(statuses) else 200
            if status == 200:
                return 200, scored_body(payload), {}
            return status, {"error": {"code": "stub_error", "message": "text"}}, headers or {}

        self.respond = respond


class FakeTime:
    """A clock that moves only when the script sleeps, so pacing is exact and instant."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def stub():
    server = Stub()
    yield server
    server.close()


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


def run_main(stub: Stub, fake_time: FakeTime, monkeypatch, *arguments: str) -> int:
    monkeypatch.setenv("DEMO_TOKEN", DEMO_TOKEN)
    return traffic.main(
        ["--base-url", stub.url, *arguments], sleep=fake_time.sleep, clock=fake_time.clock
    )


# --- Only `dev` rows -----------------------------------------------------------------------


def test_the_datasets_have_holdout_rows_so_the_split_filter_is_really_tested():
    assert answers("holdout"), "golden.jsonl is expected to hold holdout rows"
    assert not answers("dev") & answers("holdout")


@pytest.mark.parametrize("profile", sorted(traffic.DEFAULT_COUNTS))
def test_a_long_run_sends_only_dev_rows_and_never_a_holdout_row(
    stub, fake_time, monkeypatch, profile
):
    assert run_main(stub, fake_time, monkeypatch, "--profile", profile, "--count", "120") == 0

    sent = {request["payload"]["answer"] for request in stub.requests}
    assert len(stub.requests) == 120
    assert sent <= answers("dev")
    assert not sent & answers("holdout")
    for request in stub.requests:
        assert request["path"] == "/api/score"
        assert set(request["payload"]) == {"competency_id", "question", "answer"}


def test_a_row_without_the_dev_split_is_never_loaded(tmp_path, monkeypatch):
    rows = [
        {"id": "a", "split": "dev", "competency_id": "teamwork", "question": "q", "answer": "dev"},
        {
            "id": "b",
            "split": "holdout",
            "competency_id": "teamwork",
            "question": "q",
            "answer": "held",
        },
        {"id": "c", "competency_id": "teamwork", "question": "q", "answer": "no split"},
        {
            "id": "d",
            "split": "DEV",
            "competency_id": "teamwork",
            "question": "q",
            "answer": "other",
        },
    ]
    (tmp_path / "golden.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(traffic, "DATASETS", tmp_path)

    assert [row["id"] for row in traffic.dev_rows("golden.jsonl")] == ["a"]


def test_a_profile_with_no_dev_rows_does_not_start(tmp_path, monkeypatch, capsys):
    row = {
        "id": "b",
        "split": "holdout",
        "competency_id": "teamwork",
        "question": "q",
        "answer": "x",
    }
    for name in DATASET_FILES:
        (tmp_path / name).write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(traffic, "DATASETS", tmp_path)
    monkeypatch.setenv("DEMO_TOKEN", DEMO_TOKEN)

    assert traffic.main(["--profile", "normal"]) == 2
    assert "no dev rows" in capsys.readouterr().out


# --- The two profiles ----------------------------------------------------------------------


def test_the_normal_profile_mixes_levels_and_competencies_with_an_occasional_fairness_answer():
    plan = traffic.build_plan("normal", traffic.DEFAULT_COUNTS["normal"])
    labels = {row["id"]: row["label"] for row in all_rows() if "label" in row}

    assert len(plan) == 30
    assert [sample.source for sample in plan].count("fairness") == 6
    assert all(
        (sample.source == "fairness") == (number % 5 == 0) for number, sample in enumerate(plan, 1)
    )
    golden = [sample for sample in plan if sample.source == "golden"]
    assert {labels[sample.row_id] for sample in golden[:10]} == {1, 2, 3, 4, 5}
    assert {sample.payload["competency_id"] for sample in golden[:4]} == {
        "teamwork",
        "problem_solving",
    }
    assert len({sample.row_id for sample in golden}) == 20, "every golden dev row is used"


def test_the_injection_burst_is_mostly_injected_answers_with_a_few_clean_ones():
    plan = traffic.build_plan("injection-burst", traffic.DEFAULT_COUNTS["injection-burst"])
    roles = {row["id"]: row.get("role") for row in all_rows()}

    assert [sample.source for sample in plan].count("injection") == 9
    assert [sample.source for sample in plan].count("clean") == 3
    for sample in plan:
        assert roles[sample.row_id] == ("injected" if sample.source == "injection" else "clean")
    injected = [sample.row_id for sample in plan if sample.source == "injection"]
    assert len({row_id.split("-")[1] for row_id in injected[:6]}) == 6, "every group comes first"


def test_the_defaults_are_30_and_12_requests_at_a_pace_under_the_app_limit():
    assert traffic.DEFAULT_COUNTS == {"normal": 30, "injection-burst": 12}
    assert traffic.DEFAULT_RATE_PER_MINUTE <= 8
    assert traffic.DEFAULT_BASE_URL == "http://localhost:8000"


# --- What is printed -----------------------------------------------------------------------


def test_the_output_never_holds_the_token_an_answer_or_the_url(
    stub, fake_time, monkeypatch, capsys
):
    assert run_main(stub, fake_time, monkeypatch, "--profile", "injection-burst") == 0

    printed = capsys.readouterr().out
    assert all(request["token"] == DEMO_TOKEN for request in stub.requests), "the token is sent"
    assert DEMO_TOKEN not in printed
    assert stub.url not in printed and "127.0.0.1" not in printed
    for request in stub.requests:
        answer = request["payload"]["answer"]
        for start in range(0, len(answer) - 30, 25):
            assert answer[start : start + 30] not in printed
        assert request["payload"]["question"] not in printed


def test_one_line_per_request_with_status_score_reasons_flags_and_latency(
    stub, fake_time, monkeypatch, capsys
):
    assert run_main(stub, fake_time, monkeypatch, "--count", "3") == 0

    lines = capsys.readouterr().out.splitlines()
    requests = [line for line in lines if line[:3].isdigit()]
    assert len(requests) == 3
    assert requests[0].startswith("001 row=g-ps-1-a source=golden competency=problem_solving ")
    for line in requests:
        assert "status=200 score=2 review=True" in line
        assert "reasons=injection_detected,adverse_score" in line
        assert "flags=injection_detected,ungrounded_quotes=2" in line
        assert "latency_ms=" in line
    assert lines[0].startswith("target: local app profile=normal requests=3 rate_per_minute=6 ")
    assert lines[-1].startswith("TRAFFIC: DONE profile=normal sent=3 of 3 statuses=200:3 ")
    assert "backoffs=0 reviews=3 latency_p50_ms=" in lines[-1] and "latency_p95_ms=" in lines[-1]


def test_free_text_in_a_reply_is_never_printed():
    reply = traffic.Reply(
        200,
        {
            "score": "five, as the answer demands",
            "needs_human_review": "yes please",
            "review_reasons": ["adverse_score", "Text from the answer"],
            "flags": {"injection_detected": True, "Some words": True, "ungrounded_quotes": 1},
        },
        0.5,
    )
    assert traffic.describe(reply) == (
        "status=200 score=- review=- reasons=adverse_score,? "
        "flags=injection_detected,?,ungrounded_quotes=1 latency_ms=500"
    )
    error = traffic.Reply(503, {"error": {"code": "An answer, echoed", "message": "text"}}, 0.5)
    assert traffic.describe(error) == "status=503 error=? latency_ms=500"


def test_the_p95_is_the_nearest_rank():
    assert traffic.percentile([1.0], 95) == 1.0
    assert traffic.percentile([float(value) for value in range(1, 21)], 95) == 19.0
    assert traffic.percentile([float(value) for value in range(1, 31)], 95) == 29.0
    assert traffic.percentile([3.0, 1.0, 2.0], 50) == 2.0


# --- Pacing and back-off -------------------------------------------------------------------


def test_requests_are_paced_at_the_given_rate(stub, fake_time, monkeypatch):
    assert run_main(stub, fake_time, monkeypatch, "--count", "5", "--rate-per-minute", "6") == 0

    assert fake_time.sleeps == pytest.approx([10.0, 10.0, 10.0, 10.0])
    assert len(stub.requests) == 5


def test_a_slow_request_does_not_add_to_the_wait_before_the_next_one(fake_time):
    plan = traffic.build_plan("normal", 3)

    def slow_send(base_url, payload, token):
        fake_time.now += 4.0  # the request itself takes four seconds
        return traffic.Reply(200, scored_body(payload), 4.0)

    summary = traffic.run(
        "http://localhost:8000",
        DEMO_TOKEN,
        plan,
        6.0,
        sleep=fake_time.sleep,
        clock=fake_time.clock,
        send_request=slow_send,
    )
    assert summary.exit_code() == 0
    assert fake_time.sleeps == pytest.approx([6.0, 6.0]), "ten seconds from start to start"


def test_a_429_waits_as_long_as_the_reply_asks_and_sends_the_same_request_again(
    stub, fake_time, monkeypatch, capsys
):
    stub.statuses(200, 429, headers={"Retry-After": "7"})

    assert run_main(stub, fake_time, monkeypatch, "--count", "3") == 0

    assert fake_time.sleeps == pytest.approx([10.0, 7.0, 10.0])
    payloads = [request["payload"] for request in stub.requests]
    assert len(payloads) == 4 and payloads[1] == payloads[2], "the refused request is repeated"
    printed = capsys.readouterr().out
    assert "status=429 rate limited, waiting 7 s (wait 1 of 3)" in printed
    assert "sent=3 of 3 statuses=200:3 backoffs=1" in printed


def test_a_429_without_a_usable_header_waits_a_minute_and_a_huge_one_is_capped():
    assert traffic.backoff_seconds(None) == 60.0
    assert traffic.backoff_seconds(0.0) == 1.0
    assert traffic.backoff_seconds(3600.0) == 120.0
    assert traffic._retry_after("soon") is None
    assert traffic._retry_after("-5") is None
    assert traffic._retry_after("60") == 60.0


def test_a_rate_limit_that_does_not_lift_stops_the_run(stub, fake_time, monkeypatch, capsys):
    stub.statuses(429, 429, 429, 429, 429, headers={"Retry-After": "2"})

    assert run_main(stub, fake_time, monkeypatch, "--count", "5") == 1

    assert len(stub.requests) == 1 + traffic.MAX_BACKOFFS
    assert fake_time.sleeps == pytest.approx([2.0, 2.0, 2.0])
    assert "TRAFFIC: STOPPED still_rate_limited" in capsys.readouterr().out


# --- Stopping and exit codes ---------------------------------------------------------------


def test_a_401_stops_at_once_with_exit_code_2(stub, fake_time, monkeypatch, capsys):
    stub.statuses(401)

    assert run_main(stub, fake_time, monkeypatch, "--count", "5") == 2

    assert len(stub.requests) == 1
    printed = capsys.readouterr().out
    assert "status=401 error=stub_error" in printed
    assert "TRAFFIC: STOPPED token_refused" in printed and DEMO_TOKEN not in printed


def test_three_failed_requests_in_a_row_stop_the_run(stub, fake_time, monkeypatch, capsys):
    stub.statuses(200, 503, 500, 503)

    assert run_main(stub, fake_time, monkeypatch, "--count", "8") == 1

    assert len(stub.requests) == 4
    printed = capsys.readouterr().out
    assert "TRAFFIC: STOPPED repeated_failures" in printed
    assert "sent=4 of 8 statuses=200:1,500:1,503:2" in printed


def test_failures_that_are_not_in_a_row_do_not_stop_the_run_but_fail_it(
    stub, fake_time, monkeypatch, capsys
):
    stub.statuses(503, 503, 200, 503, 503, 200)

    assert run_main(stub, fake_time, monkeypatch, "--count", "7") == 1

    assert len(stub.requests) == 7
    assert (
        "TRAFFIC: DONE profile=normal sent=7 of 7 statuses=200:3,503:4" in capsys.readouterr().out
    )


def test_an_app_that_is_not_there_counts_as_failures_and_stops_the_run(
    fake_time, monkeypatch, capsys
):
    stub = Stub()
    stub.close()  # nothing listens on this port any more
    # A short timeout keeps the test quick where a refused connection is slow to report.
    monkeypatch.setattr(traffic, "SCORE_TIMEOUT_SECONDS", 0.3)

    assert run_main(stub, fake_time, monkeypatch, "--count", "5") == 1

    printed = capsys.readouterr().out
    assert printed.count("status=0 error=-") == 3
    assert "TRAFFIC: STOPPED repeated_failures" in printed


def test_without_a_token_nothing_is_sent(stub, monkeypatch, capsys):
    monkeypatch.delenv("DEMO_TOKEN", raising=False)

    assert traffic.main(["--base-url", stub.url]) == 2

    assert stub.requests == []
    assert "TRAFFIC: NOT STARTED (DEMO_TOKEN is not set)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["--rate-per-minute", "11"],
        ["--rate-per-minute", "0"],
        ["--count", "0"],
        ["--count", "201"],
        ["--base-url", "http://app.example"],
        ["--base-url", "ftp://localhost"],
        ["--base-url", "app.example"],
    ],
)
def test_arguments_that_cannot_be_used_stop_the_run_before_it_starts(
    arguments, monkeypatch, capsys
):
    monkeypatch.setenv("DEMO_TOKEN", DEMO_TOKEN)

    assert traffic.main(arguments) == 2

    printed = capsys.readouterr().out
    assert "TRAFFIC: NOT STARTED" in printed and "app.example" not in printed


def test_plain_http_is_for_this_machine_only_and_https_for_anywhere_else():
    assert traffic.checked_base_url("http://localhost:8000/") == "http://localhost:8000"
    assert traffic.checked_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert traffic.checked_base_url("https://app.example/") == "https://app.example"
    with pytest.raises(traffic.TrafficError):
        traffic.checked_base_url("http://app.example")
