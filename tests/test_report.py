import os
import tempfile
import pypdfium2 as pdfium
from report import generate_report


def test_generate_report_valid_pdf():
    mock_metrics = {
        "statement_period": "2024-01 to 2024-04",
        "months_analyzed": 4,
        "total_income": 200000.0,
        "avg_monthly_income": 50000.0,
        "monthly_income_std": 3200.0,
        "coefficient_of_variation": 0.064,
        "total_outflow": 120000.0,
        "avg_monthly_outflow": 30000.0,
        "monthly_outflow_std": 2500.0,
        "total_net_flow": 80000.0,
        "avg_monthly_net_flow": 20000.0,
        "savings_rate_pct": 40.0,
        "expense_ratio_pct": 60.0,
        "deficit_months_count": 0,
        "stability_score": 87,
        "cash_flow_score": 100,
        "risk_score": 95,
        "composite_score": 93,
        "credit_grade": "A",
        "decision": "APPROVED",
        "decision_reason": "Excellent cash flow stability with strong surplus.",
        "recommended_loan_kes": 90000.0,
        "max_monthly_repayment_kes": 15000.0,
        "betting_metrics": {
            "tx_count": 0,
            "total_spent": 0.0,
            "monthly_avg": 0.0,
            "income_pct": 0.0,
            "risk_level": "LOW",
        },
        "debt_metrics": {
            "tx_count": 2,
            "total_paid": 5000.0,
            "monthly_avg": 1250.0,
            "dsr_pct": 2.5,
            "fuliza_count": 1,
            "fuliza_total": 1500.0,
            "risk_level": "HEALTHY",
        },
        "monthly_history": [
            {"month": "2024-01", "income": 50000.0, "outflow": 30000.0, "net": 20000.0, "status": "Surplus"},
            {"month": "2024-02", "income": 48000.0, "outflow": 28000.0, "net": 20000.0, "status": "Surplus"},
            {"month": "2024-03", "income": 52000.0, "outflow": 31000.0, "net": 21000.0, "status": "Surplus"},
            {"month": "2024-04", "income": 50000.0, "outflow": 31000.0, "net": 19000.0, "status": "Surplus"},
        ],
    }

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        generate_report(mock_metrics, tmp_path)
        assert os.path.exists(tmp_path)
        assert os.path.getsize(tmp_path) > 1000

        # Verify that the PDF is valid and readable
        pdf = pdfium.PdfDocument(tmp_path)
        assert len(pdf) >= 1
        page_text = pdf[0].get_textpage().get_text_range()
        assert "M-PESA UNDERWRITING" in page_text
        assert "APPROVED" in page_text
        assert "KES 90,000.00" in page_text
        pdf.close()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
