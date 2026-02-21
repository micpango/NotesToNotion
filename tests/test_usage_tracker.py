import pytest

import app_contract as ac
import usage_tracker as ut


def test_usage_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "usage.json"
    ut.append_event(
        path,
        {
            "ts": 1700000000.0,
            "model": "gpt-5-mini",
            "input_tokens": 123,
            "output_tokens": 45,
            "filename": "IMG_0001.HEIC",
        },
    )

    data = ut.load_usage(path)
    assert "events" in data
    assert len(data["events"]) == 1
    assert data["events"][0]["input_tokens"] == 123
    assert data["events"][0]["output_tokens"] == 45


def test_usage_aggregates_last7_days_only_counts_recent_event():
    now = 1_700_000_000.0
    old_event = {
        "ts": now - (8 * 24 * 60 * 60),
        "input_tokens": 1_000_000,
        "output_tokens": 0,
    }
    recent_event = {
        "ts": now - (1 * 24 * 60 * 60),
        "input_tokens": 0,
        "output_tokens": 1_000_000,
    }
    agg = ut.aggregates([old_event, recent_event], now_ts=now)

    expected_total = ut.event_cost_usd(old_event) + ut.event_cost_usd(recent_event)
    expected_recent = ut.event_cost_usd(recent_event)
    assert agg["count"] == 2
    assert agg["total_cost"] == pytest.approx(expected_total)
    assert agg["avg_cost"] == pytest.approx(expected_total / 2)
    assert agg["last7_cost"] == pytest.approx(expected_recent)


def test_usage_cost_formula_uses_price_constants():
    event = {"input_tokens": 2000, "output_tokens": 1000}
    expected = (
        (2000 * ac.PRICE_PER_1M_INPUT_TOKENS_USD)
        + (1000 * ac.PRICE_PER_1M_OUTPUT_TOKENS_USD)
    ) / 1_000_000.0
    assert ut.event_cost_usd(event) == pytest.approx(expected)
