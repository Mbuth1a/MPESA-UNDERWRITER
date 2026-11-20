import re
import pandas as pd
from mobile_money import parse_statement, prepare


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

BETTING_PATTERN = re.compile(
    r"\b(?:betika|sportpesa|odibets|1xbet|mozzart|betway|shabiki|kwikbet|bangbet|"
    r"22bet|lotto|chezacash|betpawa|betlion|gammania|casino|betting|gambling|"
    r"290290|955100|955700|290070|290680|290059|763766|290025|600100)\b",
    re.IGNORECASE,
)

# Tightened: removed ambiguous tokens like "branch" and "asante".
DEBT_PATTERN = re.compile(
    r"(?:"
    r"\bfuliza\b|\boverdraft\b|"
    r"\bm-?shwari loan\b|\bkcb m-?pesa loan\b|"
    r"\btala\b|\bzenka\b|\bopesa\b|\bokash\b|\bkashway\b|\bzash\b|"
    r"\bkopa\b|\bsacco loan\b|\bcredit loan\b|"
    r"\b(?:loan repayment|loan payment|loan disbursement)\b"
    r")",
    re.IGNORECASE,
)

FULIZA_PATTERN = re.compile(r"\b(?:fuliza|overdraft|od loan)\b", re.IGNORECASE)

# Inflow classification patterns
INFLOW_SALARY = re.compile(r"\b(?:salary|payroll|wages|stipend)\b", re.IGNORECASE)
INFLOW_BUSINESS = re.compile(
    r"\b(?:pay bill|paybill|merchant payment|till number|buy goods|business payment)\b",
    re.IGNORECASE,
)
INFLOW_PEER = re.compile(r"\b(?:funds received from|received from)\b", re.IGNORECASE)
INFLOW_REVERSAL = re.compile(r"\b(?:reversal|reversed)\b", re.IGNORECASE)
LOAN_INFLOW = re.compile(
    r"\b(?:fuliza|m-?shwari|kcb m-?pesa|tala|branch|zenka|okash|opesa|"
    r"kashway|zash|kopa|loan disbursement|credit received)\b",
    re.IGNORECASE,
)


def classify_inflow(text: str) -> str:
    """
    Classify a transaction description into an inflow category.
    Returns one of: loan_disbursement, reversal, salary, business, peer_transfer, other.
    """
    d = text or ""
    if LOAN_INFLOW.search(d):
        return "loan_disbursement"
    if INFLOW_REVERSAL.search(d):
        return "reversal"
    if INFLOW_SALARY.search(d):
        return "salary"
    if INFLOW_BUSINESS.search(d):
        return "business"
    if INFLOW_PEER.search(d):
        return "peer_transfer"
    return "other"


# ---------------------------------------------------------------------------
# Main metrics computation
# ---------------------------------------------------------------------------

def compute_financial_metrics(df: pd.DataFrame) -> dict:
    """
    Compute comprehensive cash-flow, debt, risk, and stability metrics
    from a prepared M-Pesa transaction DataFrame.
    """
    if "paid_in" not in df.columns or "withdrawn" not in df.columns:
        return {"error": "Missing expected statement columns: 'paid_in' and 'withdrawn'."}

    # Ensure completion_time is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["completion_time"]):
        df["completion_time"] = pd.to_datetime(df["completion_time"])

    if "month" not in df.columns:
        df["month"] = df["completion_time"].dt.to_period("M").astype(str)
    else:
        df["month"] = df["month"].astype(str)

    # ------------------------------------------------------------------
    # 0. Inflow classification (NEW)
    # ------------------------------------------------------------------
    details_series = df["details"].fillna("").astype(str)
    counterparty_series = df.get("counterparty", pd.Series("", index=df.index)).fillna("").astype(str)
    text_to_search = details_series + " " + counterparty_series

    df["inflow_category"] = text_to_search.apply(classify_inflow)

    # "True income" excludes loan disbursements and reversals
    true_income_mask = df["paid_in"].gt(0) & df["inflow_category"].isin(
        ["salary", "business", "peer_transfer"]
    )
    income_df = df[true_income_mask].copy()

    if income_df.empty:
        return {"error": "No genuine income transactions found (all inflows are loans or reversals)."}

    # All unique months represented in the statement
    statement_months = sorted(df["month"].unique().tolist())
    if len(statement_months) < 2:
        return {"error": "Need at least 2 months of statement data for stability and risk analysis."}

    num_months = len(statement_months)

    # ------------------------------------------------------------------
    # 1. Monthly aggregation (now based on TRUE income)
    # ------------------------------------------------------------------
    monthly_in = income_df.groupby("month")["paid_in"].sum().reindex(statement_months, fill_value=0.0)

    expense_df = df[df["withdrawn"] > 0].copy()
    if not expense_df.empty:
        monthly_out = expense_df.groupby("month")["withdrawn"].sum().reindex(statement_months, fill_value=0.0)
    else:
        monthly_out = pd.Series(0.0, index=statement_months)

    monthly_net = monthly_in - monthly_out

    # ------------------------------------------------------------------
    # 2. Inflow metrics
    # ------------------------------------------------------------------
    total_income = float(monthly_in.sum())
    avg_monthly_income = float(monthly_in.mean())
    std_monthly_income = float(monthly_in.std(ddof=1)) if num_months > 1 else 0.0

    # ------------------------------------------------------------------
    # 3. CV with partial-month exclusion (NEW)
    # ------------------------------------------------------------------
    partial_months_excluded = []
    if num_months > 3:
        day_counts = df.groupby("month")["completion_time"].agg(
            lambda s: (s.max() - s.min()).days + 1
        )
        interior_months = statement_months[1:-1]
        full_months = [m for m in interior_months if day_counts.get(m, 0) >= 20]
        partial_months_excluded = [m for m in statement_months if m not in full_months]

        if len(full_months) >= 2:
            cv_series = monthly_in.reindex(full_months)
            cv = float(cv_series.std(ddof=1) / cv_series.mean()) if cv_series.mean() > 0 else 1.0
        else:
            cv = float(std_monthly_income / avg_monthly_income) if avg_monthly_income > 0 else 1.0
    else:
        cv = float(std_monthly_income / avg_monthly_income) if avg_monthly_income > 0 else 1.0

    # Stability score based on CV
    # CV <= 0.10 -> 100, CV >= 0.50 -> 0
    stability_score = max(0, min(100, int((1.0 - cv / 0.50) * 100)))

    # ------------------------------------------------------------------
    # 4. Outflow & net cash flow metrics
    # ------------------------------------------------------------------
    total_outflow = float(monthly_out.sum())
    avg_monthly_outflow = float(monthly_out.mean())
    std_monthly_outflow = float(monthly_out.std(ddof=1)) if num_months > 1 else 0.0

    total_net = float(monthly_net.sum())
    avg_monthly_net = float(monthly_net.mean())

    savings_rate_pct = (total_net / total_income * 100.0) if total_income > 0 else 0.0
    expense_ratio_pct = (total_outflow / total_income * 100.0) if total_income > 0 else 100.0
    deficit_months = int((monthly_net < 0).sum())

    cash_flow_score = 100
    if savings_rate_pct < 0:
        cash_flow_score -= 35
    elif savings_rate_pct < 10:
        cash_flow_score -= 15
    cash_flow_score -= int((deficit_months / num_months) * 45)
    cash_flow_score = max(0, min(100, cash_flow_score))

    # ------------------------------------------------------------------
    # 5. Betting / gambling risk (softened tiers)
    # ------------------------------------------------------------------
    betting_mask = text_to_search.str.contains(BETTING_PATTERN) & (df["withdrawn"] > 0)
    betting_tx_count = int(betting_mask.sum())
    betting_total_spent = float(df.loc[betting_mask, "withdrawn"].sum()) if betting_tx_count > 0 else 0.0
    betting_monthly_avg = betting_total_spent / num_months
    betting_income_pct = (betting_total_spent / total_income * 100.0) if total_income > 0 else 0.0

    if betting_tx_count == 0 or betting_total_spent < 500:
        betting_risk_level = "LOW"
    elif betting_income_pct < 1.0 and betting_tx_count <= 2:
        betting_risk_level = "LOW"
    elif betting_income_pct < 6.0 and betting_tx_count <= 8:
        betting_risk_level = "MEDIUM"
    else:
        betting_risk_level = "HIGH"

    # ------------------------------------------------------------------
    # 6. Debt servicing risk
    # ------------------------------------------------------------------
    debt_mask = text_to_search.str.contains(DEBT_PATTERN) & (df["withdrawn"] > 0)
    debt_tx_count = int(debt_mask.sum())
    debt_total_paid = float(df.loc[debt_mask, "withdrawn"].sum()) if debt_tx_count > 0 else 0.0
    debt_monthly_avg = debt_total_paid / num_months
    dsr_pct = (debt_monthly_avg / avg_monthly_income * 100.0) if avg_monthly_income > 0 else 0.0

    fuliza_mask = text_to_search.str.contains(FULIZA_PATTERN) & (df["withdrawn"] > 0)
    fuliza_count = int(fuliza_mask.sum())
    fuliza_total_amount = float(df.loc[fuliza_mask, "withdrawn"].sum()) if fuliza_count > 0 else 0.0

    if dsr_pct < 20.0 and fuliza_count <= 5:
        debt_risk_level = "HEALTHY"
    elif dsr_pct < 38.0 or fuliza_count <= 15:
        debt_risk_level = "MODERATE"
    else:
        debt_risk_level = "OVERLEVERAGED"

    # ------------------------------------------------------------------
    # 7. Fuliza trend (NEW)
    # ------------------------------------------------------------------
    fuliza_df = df[fuliza_mask].copy()
    fuliza_trend = []
    for m in statement_months:
        month_rows = fuliza_df[fuliza_df["month"] == m]
        fuliza_trend.append({
            "month": m,
            "count": int(len(month_rows)),
            "total": round(float(month_rows["withdrawn"].sum()) if len(month_rows) else 0.0, 2),
        })

    # Same-day repay-and-reborrow: >1 Fuliza withdrawal within same calendar day
    if not fuliza_df.empty:
        fuliza_df["day"] = fuliza_df["completion_time"].dt.date
        same_day = fuliza_df.groupby("day").size()
        same_day_reborrow_days = int((same_day > 1).sum())
    else:
        same_day_reborrow_days = 0

    # ------------------------------------------------------------------
    # 8. Overall risk score
    # ------------------------------------------------------------------
    risk_score = 100
    if betting_risk_level == "HIGH":
        risk_score -= 35
    elif betting_risk_level == "MEDIUM":
        risk_score -= 15

    if debt_risk_level == "OVERLEVERAGED":
        risk_score -= 30
    elif debt_risk_level == "MODERATE":
        risk_score -= 12

    if fuliza_count > 15:
        risk_score -= 15
    elif fuliza_count > 6:
        risk_score -= 8

    if total_net < 0:
        risk_score -= 15

    risk_score = max(0, min(100, risk_score))

    # ------------------------------------------------------------------
    # 9. Composite score & decision
    # ------------------------------------------------------------------
    composite_score = int(0.35 * stability_score + 0.35 * cash_flow_score + 0.30 * risk_score)
    composite_score = max(0, min(100, composite_score))

    if composite_score >= 75:
        credit_grade = "A"
        decision = "APPROVED"
        decision_reason = "Strong cash flow surplus, consistent monthly income, and minimal debt or gambling exposure."
    elif composite_score >= 60:
        credit_grade = "B"
        decision = "CONDITIONAL APPROVAL"
        decision_reason = "Healthy income baseline with moderate volatility or manageable ongoing debt obligations."
    elif composite_score >= 45:
        credit_grade = "C"
        decision = "MANUAL REVIEW REQUIRED"
        decision_reason = "Elevated risk factors detected: high debt service ratio, deficit months, or erratic income swings."
    else:
        credit_grade = "D"
        decision = "DECLINED"
        decision_reason = "High credit risk due to severe income volatility, persistent cash deficit, or heavy gambling/debt dependency."

    if total_net < 0 or (deficit_months / num_months) >= 0.5:
        if decision in ["APPROVED", "CONDITIONAL APPROVAL"]:
            decision = "MANUAL REVIEW REQUIRED"
            credit_grade = "C"
            decision_reason = "Elevated risk: Chronic cash-flow deficit detected (outflows exceed inflows)."
        if total_net < 0 and savings_rate_pct < -20:
            decision = "DECLINED"
            credit_grade = "D"
            decision_reason = "High credit risk: Severe negative cash flow deficit across statement period."

    # ------------------------------------------------------------------
    # 10. Loan recommendation
    # ------------------------------------------------------------------
    surplus_cap = max(0.0, avg_monthly_net * 0.50) if avg_monthly_net > 0 else (avg_monthly_income * 0.10)
    raw_capacity = min(avg_monthly_income * 0.30, surplus_cap) - (debt_monthly_avg * 0.35)
    raw_capacity = max(0.0, raw_capacity)

    score_factor = 0.5 + 0.5 * (composite_score / 100.0)
    recommended_monthly_repayment = round(raw_capacity * score_factor, 2)

    if decision == "DECLINED" or total_net < 0:
        recommended_loan = 0.0
        recommended_monthly_repayment = 0.0
    else:
        recommended_loan = round(recommended_monthly_repayment * 6, 2)

    loan_options = {
        "3_months": round(recommended_monthly_repayment * 3, 2),
        "6_months": recommended_loan,
        "12_months": round(recommended_monthly_repayment * 12, 2),
    }

    # ------------------------------------------------------------------
    # 11. Monthly history
    # ------------------------------------------------------------------
    monthly_history = []
    for m in statement_months:
        inc = float(monthly_in.get(m, 0.0))
        out = float(monthly_out.get(m, 0.0))
        net = inc - out
        monthly_history.append({
            "month": m,
            "income": round(inc, 2),
            "outflow": round(out, 2),
            "net": round(net, 2),
            "status": "Surplus" if net >= 0 else "Deficit",
        })

    # ------------------------------------------------------------------
    # 12. Category breakdown
    # ------------------------------------------------------------------
    category_breakdown = []
    if "category" in df.columns:
        cat_grouped = df[df["withdrawn"] > 0].groupby("category")["withdrawn"].agg(["sum", "count"]).reset_index()
        total_cat_spend = float(cat_grouped["sum"].sum())
        for _, row in cat_grouped.sort_values(by="sum", ascending=False).iterrows():
            spend = float(row["sum"])
            share = round((spend / total_cat_spend * 100.0), 1) if total_cat_spend > 0 else 0.0
            category_breakdown.append({
                "category": str(row["category"]),
                "spent": round(spend, 2),
                "share_pct": share,
                "tx_count": int(row["count"]),
            })
    else:
        category_breakdown.append({
            "category": "General Spend",
            "spent": round(total_outflow, 2),
            "share_pct": 100.0,
            "tx_count": len(expense_df),
        })

    # ------------------------------------------------------------------
    # 13. Inflow breakdown (NEW)
    # ------------------------------------------------------------------
    inflow_breakdown = []
    if not income_df.empty:
        grouped = income_df.groupby("inflow_category")["paid_in"].agg(["sum", "count"]).reset_index()
        for _, row in grouped.iterrows():
            inflow_breakdown.append({
                "category": str(row["inflow_category"]),
                "total": round(float(row["sum"]), 2),
                "tx_count": int(row["count"]),
            })

    # ------------------------------------------------------------------
    # 14. Score breakdown (NEW)
    # ------------------------------------------------------------------
    score_breakdown = []
    if betting_risk_level == "HIGH":
        score_breakdown.append({"factor": "Betting activity", "impact": -35, "detail": "HIGH tier"})
    elif betting_risk_level == "MEDIUM":
        score_breakdown.append({"factor": "Betting activity", "impact": -15, "detail": "MEDIUM tier"})

    if debt_risk_level == "OVERLEVERAGED":
        score_breakdown.append({"factor": "Debt service ratio", "impact": -30, "detail": f"DSR {dsr_pct:.1f}%"})
    elif debt_risk_level == "MODERATE":
        score_breakdown.append({"factor": "Debt service ratio", "impact": -12, "detail": f"DSR {dsr_pct:.1f}%"})

    if fuliza_count > 15:
        score_breakdown.append({"factor": "Fuliza usage", "impact": -15, "detail": f"{fuliza_count} items"})
    elif fuliza_count > 6:
        score_breakdown.append({"factor": "Fuliza usage", "impact": -8, "detail": f"{fuliza_count} items"})

    if total_net < 0:
        score_breakdown.append({"factor": "Negative net cash flow", "impact": -15, "detail": f"KES {total_net:,.0f}"})

    # ------------------------------------------------------------------
    # Return
    # ------------------------------------------------------------------
    return {
        "months_analyzed": num_months,
        "statement_period": f"{statement_months[0]} to {statement_months[-1]}",
        "partial_months_excluded": partial_months_excluded,
        "total_income": round(total_income, 2),
        "avg_monthly_income": round(avg_monthly_income, 2),
        "monthly_income_std": round(std_monthly_income, 2),
        "coefficient_of_variation": round(cv, 3),
        "total_outflow": round(total_outflow, 2),
        "avg_monthly_outflow": round(avg_monthly_outflow, 2),
        "monthly_outflow_std": round(std_monthly_outflow, 2),
        "total_net_flow": round(total_net, 2),
        "avg_monthly_net_flow": round(avg_monthly_net, 2),
        "savings_rate_pct": round(savings_rate_pct, 1),
        "expense_ratio_pct": round(expense_ratio_pct, 1),
        "deficit_months_count": deficit_months,
        "stability_score": stability_score,
        "cash_flow_score": cash_flow_score,
        "risk_score": risk_score,
        "composite_score": composite_score,
        "credit_grade": credit_grade,
        "decision": decision,
        "decision_reason": decision_reason,
        "recommended_loan_kes": recommended_loan,
        "max_monthly_repayment_kes": recommended_monthly_repayment,
        "loan_options": loan_options,
        "betting_metrics": {
            "tx_count": betting_tx_count,
            "total_spent": round(betting_total_spent, 2),
            "monthly_avg": round(betting_monthly_avg, 2),
            "income_pct": round(betting_income_pct, 2),
            "risk_level": betting_risk_level,
        },
        "debt_metrics": {
            "tx_count": debt_tx_count,
            "total_paid": round(debt_total_paid, 2),
            "monthly_avg": round(debt_monthly_avg, 2),
            "dsr_pct": round(dsr_pct, 2),
            "fuliza_count": fuliza_count,
            "fuliza_total": round(fuliza_total_amount, 2),
            "risk_level": debt_risk_level,
        },
        "fuliza_trend": fuliza_trend,
        "same_day_reborrow_days": same_day_reborrow_days,
        "inflow_breakdown": inflow_breakdown,
        "score_breakdown": score_breakdown,
        "monthly_history": monthly_history,
        "category_breakdown": category_breakdown,
        "total_transactions": len(df),
    }


def analyze_statement(pdf_path: str, password: str) -> dict:
    """
    Parse an M-Pesa PDF statement and compute cash-flow and underwriting metrics.
    """
    try:
        statement = parse_statement(pdf_path, password=password)
    except Exception as e:
        err_msg = str(e)
        if "password" in err_msg.lower() or "decrypt" in err_msg.lower():
            return {"error": "Failed to decrypt PDF. Please verify your statement password."}
        return {"error": f"Error parsing statement: {err_msg}"}

    try:
        df = prepare(statement.transactions)
    except Exception as e:
        return {"error": f"Error normalizing transaction data: {str(e)}"}

    result = compute_financial_metrics(df)
    if "error" not in result:
        result["provider"] = statement.provider
        result["pages"] = statement.pages
        if statement.account:
            result["account"] = statement.account
    return result