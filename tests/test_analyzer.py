import pytest
import pandas as pd
from analyzer import compute_financial_metrics


def _build_mock_df(months_count=4, monthly_income=50000.0, monthly_outflow=30000.0, extra_txs=None):
    """Helper to build synthetic transaction DataFrame over multiple months."""
    rows = []
    base_date = pd.Timestamp("2024-01-01")

    for m in range(months_count):
        date_in = base_date + pd.DateOffset(months=m, days=5)
        date_out = base_date + pd.DateOffset(months=m, days=15)
        month_str = date_in.strftime("%Y-%m")

        # Income transaction
        rows.append({
            "receipt_no": f"REC_IN_{m}",
            "completion_time": date_in,
            "month": month_str,
            "details": "Funds received from Business Client",
            "counterparty": "Business Client",
            "paid_in": float(monthly_income),
            "withdrawn": 0.0,
            "category": "Money Received",
            "status": "Completed",
        })

        # Outflow transaction
        rows.append({
            "receipt_no": f"REC_OUT_{m}",
            "completion_time": date_out,
            "month": month_str,
            "details": "Customer Transfer to Supplier",
            "counterparty": "Supplier",
            "paid_in": 0.0,
            "withdrawn": float(monthly_outflow),
            "category": "Merchant Payment",
            "status": "Completed",
        })

    if extra_txs:
        rows.extend(extra_txs)

    return pd.DataFrame(rows)


def test_healthy_borrower_approved():
    df = _build_mock_df(months_count=4, monthly_income=60000.0, monthly_outflow=35000.0)
    res = compute_financial_metrics(df)

    assert "error" not in res
    assert res["months_analyzed"] == 4
    assert res["total_income"] == 240000.0
    assert res["avg_monthly_income"] == 60000.0
    assert res["total_outflow"] == 140000.0
    assert res["avg_monthly_net_flow"] == 25000.0
    assert res["stability_score"] >= 80
    assert res["betting_metrics"]["risk_level"] == "LOW"
    assert res["debt_metrics"]["risk_level"] == "HEALTHY"
    assert res["decision"] == "APPROVED"
    assert res["recommended_loan_kes"] > 0


def test_gambling_flag_detected():
    extra = [
        {
            "receipt_no": "BET1",
            "completion_time": pd.Timestamp("2024-01-10"),
            "month": "2024-01",
            "details": "Pay Bill to 290290 - Betika",
            "counterparty": "Betika",
            "paid_in": 0.0,
            "withdrawn": 12000.0,
            "category": "Bills & Paybill",
            "status": "Completed",
        },
        {
            "receipt_no": "BET2",
            "completion_time": pd.Timestamp("2024-02-12"),
            "month": "2024-02",
            "details": "Pay Bill to 955100 - SportPesa",
            "counterparty": "SportPesa",
            "paid_in": 0.0,
            "withdrawn": 15000.0,
            "category": "Bills & Paybill",
            "status": "Completed",
        },
    ]
    df = _build_mock_df(months_count=3, monthly_income=50000.0, monthly_outflow=20000.0, extra_txs=extra)
    res = compute_financial_metrics(df)

    assert "error" not in res
    assert res["betting_metrics"]["tx_count"] == 2
    assert res["betting_metrics"]["total_spent"] == 27000.0
    assert res["betting_metrics"]["risk_level"] in ["MEDIUM", "HIGH"]
    assert res["risk_score"] < 100


def test_overleveraged_debt_detected():
    extra = []
    # Add multiple Fuliza overdraft deductions and digital credit payments
    for i in range(12):
        extra.append({
            "receipt_no": f"FUL_{i}",
            "completion_time": pd.Timestamp("2024-01-15") + pd.DateOffset(days=i),
            "month": "2024-01",
            "details": "Fuliza M-Pesa Overdraft Repayment",
            "counterparty": "Fuliza",
            "paid_in": 0.0,
            "withdrawn": 2500.0,
            "category": "Savings & Loans",
            "status": "Completed",
        })

    df = _build_mock_df(months_count=3, monthly_income=40000.0, monthly_outflow=15000.0, extra_txs=extra)
    res = compute_financial_metrics(df)

    assert "error" not in res
    assert res["debt_metrics"]["fuliza_count"] >= 10
    assert res["debt_metrics"]["risk_level"] in ["MODERATE", "OVERLEVERAGED"]


def test_negative_cash_flow_penalty():
    # Outflow higher than income
    df = _build_mock_df(months_count=3, monthly_income=20000.0, monthly_outflow=35000.0)
    res = compute_financial_metrics(df)

    assert "error" not in res
    assert res["total_net_flow"] < 0
    assert res["deficit_months_count"] == 3
    assert res["cash_flow_score"] < 50
    assert res["decision"] in ["MANUAL REVIEW REQUIRED", "DECLINED"]


def test_insufficient_data_error():
    # Only 1 month of data
    df = _build_mock_df(months_count=1, monthly_income=50000.0, monthly_outflow=20000.0)
    res = compute_financial_metrics(df)
    assert "error" in res
    assert "at least 2 months" in res["error"].lower()


def test_no_income_error():
    # No incoming transactions
    df = pd.DataFrame([
        {
            "receipt_no": "REC1",
            "completion_time": pd.Timestamp("2024-01-10"),
            "month": "2024-01",
            "details": "Withdrawal",
            "paid_in": 0.0,
            "withdrawn": 5000.0,
            "status": "Completed",
        },
        {
            "receipt_no": "REC2",
            "completion_time": pd.Timestamp("2024-02-10"),
            "month": "2024-02",
            "details": "Withdrawal",
            "paid_in": 0.0,
            "withdrawn": 3000.0,
            "status": "Completed",
        },
    ])
    res = compute_financial_metrics(df)
    assert "error" in res
    assert "no incoming transactions" in res["error"].lower()
