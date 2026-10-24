import json
import textwrap

import pytest

import merchant_eval.golden as golden_mod
from merchant_eval import run as run_mod


@pytest.fixture
def eval_dir(tmp_path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        textwrap.dedent("""
        cases:
          - id: good
            question: Revenue in December 2020?
            expect_tools: [get_sales_summary]
            golden:
              - tool: get_sales_summary
                args: {start_date: "2020-12-01", end_date: "2020-12-31"}
                answer_must_contain: [revenue, orders]
          - id: bad
            question: Forecast February 2021 revenue.
            expect_tools: []
          - id: nofixture
            question: Something never recorded.
    """)
    )
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    summary = {
        "revenue": 123456.78,
        "currency": "USD",
        "orders": 2345,
        "sessions": 44567,
        "conversion_rate": 0.0526,
        "meta": {"clamped": False, "sql_hash": "3f9a1c2b4d5e6f70", "bytes_processed": 1},
    }
    (fixtures / "good.json").write_text(
        json.dumps(
            {
                "id": "good",
                "question": "Revenue in December 2020?",
                "answer": "December 2020 revenue was $123,456.78 from 2,345 orders (5.26% conversion).",
                "tool_calls": [
                    {
                        "name": "get_sales_summary",
                        "args": {"start_date": "2020-12-01", "end_date": "2020-12-31"},
                        "response": summary,
                    }
                ],
                "model": "gemini-3.5-flash",
                "events": 4,
                "duration_s": 2.5,
                "golden_responses": [
                    {
                        "tool": "get_sales_summary",
                        "args": {"start_date": "2020-12-01", "end_date": "2020-12-31"},
                        "response": summary,
                    }
                ],
            }
        )
    )
    (fixtures / "bad.json").write_text(
        json.dumps(
            {
                "id": "bad",
                "question": "Forecast February 2021 revenue.",
                "answer": "I expect about $150,000 in February 2021, up 20%.",
                "tool_calls": [],
                "model": "gemini-3.5-flash",
                "events": 1,
            }
        )
    )
    return tmp_path, cases, fixtures


def test_replay_exit_code_and_report(eval_dir, capsys):
    tmp_path, cases, fixtures = eval_dir
    reports = tmp_path / "reports"
    code = run_mod.main(
        [
            "--replay",
            "--cases",
            str(cases),
            "--fixtures",
            str(fixtures),
            "--reports",
            str(reports),
        ]
    )
    assert code == 1
    (json_path,) = reports.glob("*.json")
    data = json.loads(json_path.read_text())
    by_id = {c["id"]: c for c in data["cases"]}
    assert set(by_id) == {"good", "bad", "nofixture"}
    assert by_id["good"]["status"] == "pass"
    assert by_id["good"]["golden"][0]["ok"] is True  # saved golden responses, no live tool
    assert by_id["good"]["model"] == "gemini-3.5-flash"
    assert by_id["bad"]["status"] == "fail"
    assert [u["raw"] for u in by_id["bad"]["grounding"]["ungrounded"]] == ["$150,000", "20%"]
    assert by_id["nofixture"]["status"] == "skip"
    assert data["mode"] == "replay"
    md = next(reports.glob("*.md")).read_text()
    assert "| good | OK |" in md and "| bad | FAIL |" in md and "| nofixture | SKIP |" in md
    out = capsys.readouterr().out
    assert "1/3 passed, 1 failed" in out


def test_replay_only_passing_case_exits_zero(eval_dir):
    _tmp_path, cases, fixtures = eval_dir
    code = run_mod.main(
        [
            "--replay",
            "--cases",
            str(cases),
            "--fixtures",
            str(fixtures),
            "--only",
            "good",
            "--no-report",
        ]
    )
    assert code == 0


def test_fail_fast_stops_after_first_failure(eval_dir, capsys):
    _tmp_path, cases, fixtures = eval_dir
    code = run_mod.main(
        [
            "--replay",
            "--cases",
            str(cases),
            "--fixtures",
            str(fixtures),
            "--no-report",
            "--fail-fast",
            "--only",
            "bad,nofixture",
        ]
    )
    assert code == 1
    table = capsys.readouterr().out.split("case")[-1]
    assert "bad" in table and "nofixture" not in table  # stopped after the first failure


def test_unknown_case_id_is_usage_error(eval_dir):
    _tmp_path, cases, _fixtures = eval_dir
    assert run_mod.main(["--replay", "--cases", str(cases), "--only", "zzz"]) == 2
    assert run_mod.main(["--record", "--replay", "--cases", str(cases)]) == 2


def test_live_mode_records_fixture_with_fake_agent(eval_dir, monkeypatch):
    """Live path with ask_sync and tools monkeypatched: fixture written, golden saved."""
    tmp_path, cases, _fixtures = eval_dir
    from dataclasses import dataclass, field

    import merchant_eval.golden as golden_mod

    @dataclass
    class ToolCall:
        name: str
        args: dict = field(default_factory=dict)
        response: dict = field(default_factory=dict)

    @dataclass
    class AskResult:
        question: str
        answer: str
        tool_calls: list
        model: str = "fake"
        events: int = 2

    summary = {"revenue": 10.0, "orders": 2, "meta": {"clamped": False}}

    def fake_ask(question, **kw):
        return AskResult(
            question,
            "Revenue $10.00 from 2 orders.",
            [ToolCall("get_sales_summary", {"start_date": "a", "end_date": "b"}, summary)],
        )

    monkeypatch.setattr(run_mod, "_ask", fake_ask)
    monkeypatch.setattr(
        golden_mod, "tool_registry", {"get_sales_summary": lambda start_date, end_date: summary}
    )
    out_fixtures = tmp_path / "recorded"
    code = run_mod.main(
        [
            "--cases",
            str(cases),
            "--only",
            "good",
            "--record",
            "--fixtures",
            str(out_fixtures),
            "--no-report",
        ]
    )
    assert code == 0
    fx = json.loads((out_fixtures / "good.json").read_text())
    assert fx["answer"].startswith("Revenue $10.00")
    assert fx["tool_calls"][0]["response"]["revenue"] == 10.0
    assert fx["golden_responses"][0]["response"] == summary
    assert fx["model"] == "fake" and fx["events"] == 2


def test_live_mode_agent_exception_is_error_record(eval_dir, monkeypatch):
    tmp_path, cases, _fixtures = eval_dir

    def boom(question, **kw):
        raise RuntimeError("no api key")

    monkeypatch.setattr(run_mod, "_ask", boom)
    reports = tmp_path / "r"
    code = run_mod.main(["--cases", str(cases), "--only", "bad", "--reports", str(reports)])
    assert code == 1
    data = json.loads(next(reports.glob("*.json")).read_text())
    assert data["cases"][0]["status"] == "error"
    assert "no api key" in data["cases"][0]["error"]


def test_repo_root_resolution():
    assert run_mod.REPO_ROOT.name == "merchant-analyst-agent"
    assert run_mod.AGENT_DIR.name == "agent"
    assert run_mod.DEFAULT_CASES == run_mod.REPO_ROOT / "eval" / "cases.yaml"


# --------------------------------------------------------------------------
# Retry / pacing
# --------------------------------------------------------------------------



def test_is_retryable_classifies_quota_and_overload():
    assert run_mod.is_retryable(RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 21.9s."))
    assert run_mod.is_retryable(RuntimeError("503 UNAVAILABLE. high demand"))
    assert run_mod.is_retryable(RuntimeError("504 DEADLINE_EXCEEDED."))
    assert not run_mod.is_retryable(ValueError("bad date"))


def test_retry_delay_parses_hint_and_caps():
    assert run_mod.retry_delay(RuntimeError("Please retry in 21.95s")) == 23.95
    assert run_mod.retry_delay(RuntimeError("'retryDelay': '25s'")) == 27.0
    assert run_mod.retry_delay(RuntimeError("retry in 200s")) == 90.0
    with pytest.raises(run_mod.QuotaExhausted):
        run_mod.retry_delay(RuntimeError("retry in 500s"))
    assert run_mod.retry_delay(RuntimeError("nothing useful")) == 30.0


def test_ask_with_retry_retries_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def flaky(question, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 5s.")
        return f"answer to {question}"

    out = run_mod.ask_with_retry(
        "q", retries=3, sleep=slept.append, log=lambda *_: None, ask=flaky
    )
    assert out == "answer to q"
    assert calls["n"] == 3
    assert slept == [7.0, 7.0]


def test_ask_with_retry_gives_up_and_does_not_retry_other_errors():
    slept: list[float] = []

    def always_quota(question, **kw):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    def bad_args(question, **kw):
        raise ValueError("nope")

    with pytest.raises(RuntimeError):
        run_mod.ask_with_retry("q", retries=2, sleep=slept.append, log=lambda *_: None, ask=always_quota)
    assert len(slept) == 2
    with pytest.raises(ValueError):
        run_mod.ask_with_retry("q", retries=2, sleep=slept.append, log=lambda *_: None, ask=bad_args)
    assert len(slept) == 2


def test_daily_quota_raises_quota_exhausted():
    daily = RuntimeError(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: generativelanguage.googleapis.com/"
        "generate_content_free_tier_requests, limit: 20, model: gemini-x, description: Generate "
        "content requests per day limit exceeded on Free Tier. Please retry in 13h26m47.75s."
    )
    with pytest.raises(run_mod.QuotaExhausted) as ei:
        run_mod.retry_delay(daily)
    assert "limit 20" in str(ei.value) and "gemini-x" in str(ei.value)
    long_wait = RuntimeError("503 UNAVAILABLE. Please retry in 1h0m5s.")
    with pytest.raises(run_mod.QuotaExhausted):
        run_mod.retry_delay(long_wait)
    assert run_mod.retry_delay(RuntimeError("Please retry in 0h2m5.5s")) == 90.0


def test_run_cases_stops_on_quota_exhausted(monkeypatch, tmp_path):
    cases = [
        golden_mod.Case(id=f"c{i}", question=f"q{i}", expect_tools=[], golden=[]) for i in range(4)
    ]
    calls: list[str] = []

    def fake_ask(question, **kw):
        calls.append(question)
        if len(calls) == 2:
            raise RuntimeError("429 ... requests per day limit exceeded ... retry in 10h0m0s")
        raise ValueError("other failure")

    monkeypatch.setattr(run_mod, "_ask", fake_ask)
    records = run_mod.run_cases(
        cases, fixtures_dir=tmp_path, retries=3, sleep=lambda s: None, log=lambda *_: None
    )
    assert calls == ["q0", "q1"]
    assert [r["status"] for r in records] == ["error", "error", "skip", "skip"]
    assert records[1]["error"].startswith("quota exhausted")
    assert "skipped: quota exhausted" in records[2]["error"]
