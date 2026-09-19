from datetime import date

import pytest

from siteplan.llm import BudgetExceeded, Budgets, DailyLedger, Meter, Usage, estimate_tokens


def test_ledger_persists_per_day(tmp_path):
    day = date(2026, 9, 19)
    DailyLedger(tmp_path, day).add(120)
    assert DailyLedger(tmp_path, day).add(30) == 150
    assert DailyLedger(tmp_path, date(2026, 9, 20)).used() == 0


def test_allowance_is_the_tightest_remaining_budget(tmp_path):
    meter = Meter(Budgets(per_step_tokens=500, per_run_tokens=300, per_day_tokens=1000),
                  DailyLedger(tmp_path))
    assert meter.allowance("extract") == 300
    meter.charge("extract", Usage(100, 50))
    assert meter.allowance("extract") == 150
    assert meter.allowance("explain") == 150


@pytest.mark.parametrize(
    ("budgets", "scope"),
    [
        (Budgets(per_step_tokens=100, per_run_tokens=1000, per_day_tokens=9000), "per-step"),
        (Budgets(per_step_tokens=1000, per_run_tokens=100, per_day_tokens=9000), "per-run"),
        (Budgets(per_step_tokens=1000, per_run_tokens=1000, per_day_tokens=100), "per-day"),
    ],
)
def test_crossing_any_budget_halts(tmp_path, budgets, scope):
    meter = Meter(budgets, DailyLedger(tmp_path))
    with pytest.raises(BudgetExceeded) as err:
        meter.charge("extract", Usage(100, 50))
    assert err.value.scope == scope


def test_no_call_is_allowed_once_a_budget_is_spent(tmp_path):
    ledger = DailyLedger(tmp_path)
    ledger.add(100)
    meter = Meter(Budgets(per_step_tokens=1000, per_run_tokens=1000, per_day_tokens=100), ledger)
    with pytest.raises(BudgetExceeded, match="per-day"):
        meter.allowance("extract")


def test_a_prompt_that_alone_would_cross_the_budget_is_never_sent(tmp_path):
    meter = Meter(Budgets(per_step_tokens=500, per_run_tokens=5000, per_day_tokens=9000),
                  DailyLedger(tmp_path))
    assert meter.allowance("explain", prompt_tokens=200) == 300
    with pytest.raises(BudgetExceeded, match="per-step"):
        meter.allowance("explain", prompt_tokens=600)


def test_token_estimate_errs_high():
    messages = [{"role": "user", "content": "x" * 300}]
    assert estimate_tokens(messages) >= 100


def test_concurrent_runs_never_lose_ledger_updates(tmp_path):
    import threading

    ledger_dir = tmp_path / "usage"
    day = date(2026, 9, 19)

    def spend():
        for _ in range(100):
            DailyLedger(ledger_dir, day).add(1)

    threads = [threading.Thread(target=spend) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert DailyLedger(ledger_dir, day).used() == 400
