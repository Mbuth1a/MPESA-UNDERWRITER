import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Rect, String, Group
from reportlab.graphics.charts.barcharts import VerticalBarChart


def _create_monthly_chart(monthly_history: list) -> Drawing:
    """Generate a clean vector bar chart comparing monthly income vs. outflows."""
    if not monthly_history:
        return None

    chart_data_history = monthly_history[-8:]
    months = [item["month"] for item in chart_data_history]
    incomes = [item["income"] for item in chart_data_history]
    outflows = [item["outflow"] for item in chart_data_history]

    max_val = max(max(incomes + [1]), max(outflows + [1]))

    drawing = Drawing(480, 130)
    chart = VerticalBarChart()
    chart.x = 45
    chart.y = 20
    chart.height = 90
    chart.width = 410
    chart.data = [incomes, outflows]
    chart.categoryAxis.categoryNames = months
    chart.categoryAxis.labels.fontSize = 7.5
    chart.categoryAxis.labels.dy = -10
    chart.valueAxis.labels.fontSize = 7.5
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max_val * 1.15
    chart.bars[0].fillColor = colors.HexColor("#00843D")
    chart.bars[1].fillColor = colors.HexColor("#E21836")
    chart.barSpacing = 2
    chart.groupSpacing = 8

    legend_income = Rect(45, 118, 10, 8, fillColor=colors.HexColor("#00843D"), strokeColor=None)
    legend_income_text = String(60, 119, "Monthly Inflow (KES)", fontSize=7.5, fillColor=colors.HexColor("#334155"))
    legend_outflow = Rect(170, 118, 10, 8, fillColor=colors.HexColor("#E21836"), strokeColor=None)
    legend_outflow_text = String(185, 119, "Monthly Outflow (KES)", fontSize=7.5, fillColor=colors.HexColor("#334155"))

    drawing.add(chart)
    drawing.add(legend_income)
    drawing.add(legend_income_text)
    drawing.add(legend_outflow)
    drawing.add(legend_outflow_text)
    return drawing


def _risk_color(level: str):
    """Map a risk level string to a colour tuple for table cells."""
    level = (level or "").upper()
    if level in ("LOW", "HEALTHY"):
        return colors.HexColor("#ecfdf5"), colors.HexColor("#00843D")
    if level in ("MEDIUM", "MODERATE"):
        return colors.HexColor("#fffbeb"), colors.HexColor("#b45309")
    return colors.HexColor("#fff1f2"), colors.HexColor("#E21836")


def _make_section_table(rows, header_bg, col_widths):
    """Small helper to build a consistently styled table."""
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]
    tbl.setStyle(TableStyle(style))
    return tbl


def generate_report(data: dict, output_path: str):
    """
    Generate an underwriting-grade financial assessment PDF report
    with embedded charts, risk flags, and loan recommendations.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
    )

    styles = getSampleStyleSheet()

    header_title_style = ParagraphStyle(
        "HeaderTitle", fontName="Helvetica-Bold", fontSize=15, leading=18,
        textColor=colors.HexColor("#064E3B"),
    )
    header_sub_style = ParagraphStyle(
        "HeaderSubtitle", fontName="Helvetica", fontSize=8.5, leading=11,
        textColor=colors.HexColor("#64748b"),
    )
    section_title = ParagraphStyle(
        "SectionTitle", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
        textColor=colors.HexColor("#064E3B"), spaceBefore=8, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "BodySmall", fontName="Helvetica", fontSize=8, leading=11,
        textColor=colors.HexColor("#334155"),
    )
    sub_body_style = ParagraphStyle(
        "BodySmaller", fontName="Helvetica", fontSize=7.5, leading=10,
        textColor=colors.HexColor("#64748b"),
    )

    decision = data.get("decision", "REVIEW")
    if decision == "APPROVED":
        dec_bg, dec_border, dec_text_color = colors.HexColor("#ecfdf5"), colors.HexColor("#00843D"), colors.HexColor("#00843D")
    elif decision == "CONDITIONAL APPROVAL":
        dec_bg, dec_border, dec_text_color = colors.HexColor("#fffbeb"), colors.HexColor("#f59e0b"), colors.HexColor("#b45309")
    elif decision == "MANUAL REVIEW REQUIRED":
        dec_bg, dec_border, dec_text_color = colors.HexColor("#f0fdf4"), colors.HexColor("#00843D"), colors.HexColor("#006E33")
    else:
        dec_bg, dec_border, dec_text_color = colors.HexColor("#fff1f2"), colors.HexColor("#E21836"), colors.HexColor("#E21836")

    decision_p_style = ParagraphStyle(
        "DecisionTitle", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=dec_text_color,
    )
    decision_reason_style = ParagraphStyle(
        "DecisionReason", fontName="Helvetica", fontSize=8.5, leading=12,
        textColor=colors.HexColor("#1e293b"),
    )

    story = []

    # 0. Brand accent stripe
    accent_bar = Table([["", ""]], colWidths=[4.7 * inch, 2.5 * inch], rowHeights=[3])
    accent_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#00843D")),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#E21836")),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(accent_bar)
    story.append(Spacer(1, 0.08 * inch))

    # 1. Header
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    header_table = Table(
        [[
            Paragraph("<b>M-PESA UNDERWRITING & FINANCIAL PROFILE</b>", header_title_style),
            Paragraph(f"<b>Generated:</b> {now_str}<br/><b>Statement:</b> {data.get('statement_period', 'N/A')}", header_sub_style),
        ]],
        colWidths=[4.2 * inch, 2.5 * inch],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)

    partial_excluded = data.get("partial_months_excluded") or []
    if partial_excluded:
        story.append(Paragraph(
            f"<i>Note: stability metrics exclude partial months: {', '.join(partial_excluded)}.</i>",
            sub_body_style,
        ))
    story.append(Spacer(1, 0.1 * inch))

    # 2. Decision callout
    decision_box_content = [
        [
            Paragraph(f"<b>UNDERWRITING DECISION: {decision}</b>", decision_p_style),
            Paragraph(f"<b>Credit Grade:</b> {data.get('credit_grade', 'N/A')} &nbsp;|&nbsp; <b>Composite Score:</b> {data.get('composite_score', 0)}/100", decision_p_style),
        ],
        [
            Paragraph(f"<b>Assessment:</b> {data.get('decision_reason', '')}", decision_reason_style),
            Paragraph(
                f"<b>Recommended Loan:</b> KES {data.get('recommended_loan_kes', 0):,.2f}<br/>"
                f"<b>Max Monthly Installment:</b> KES {data.get('max_monthly_repayment_kes', 0):,.2f}",
                decision_reason_style,
            ),
        ],
    ]
    dec_tbl = Table(decision_box_content, colWidths=[4.1 * inch, 2.6 * inch])
    dec_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), dec_bg),
        ("BOX", (0, 0), (-1, -1), 1, dec_border),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(dec_tbl)
    story.append(Spacer(1, 0.12 * inch))

    # 3. Core metrics + risk
    profile_data = [
        ["Cash-Flow Metric", "Value", "Benchmark"],
        ["Months Analyzed", str(data.get("months_analyzed", 0)), "Min 2 Months"],
        ["Total Income (KES)", f"{data.get('total_income', 0):,.2f}", "True income only"],
        ["Average Monthly Income", f"KES {data.get('avg_monthly_income', 0):,.2f}", "Baseline"],
        ["Average Monthly Outflow", f"KES {data.get('avg_monthly_outflow', 0):,.2f}", "Outflows"],
        ["Net Monthly Cash Flow", f"KES {data.get('avg_monthly_net_flow', 0):,.2f}", "Surplus / Deficit"],
        ["Savings / Surplus Margin", f"{data.get('savings_rate_pct', 0):.1f}%", "> 15% Healthy"],
        ["Income Stability Score", f"{data.get('stability_score', 0)} / 100", "> 70 Stable"],
        ["Income Volatility (CV)", f"{data.get('coefficient_of_variation', 0):.3f}", "< 0.30 Low"],
    ]

    betting = data.get("betting_metrics", {})
    debt = data.get("debt_metrics", {})

    risk_data = [
        ["Risk Indicator", "Metric Value", "Risk Level"],
        ["Betting / Gambling Spend", f"KES {betting.get('total_spent', 0):,.2f} ({betting.get('income_pct', 0):.1f}% Inc)", betting.get("risk_level", "LOW")],
        ["Betting Transactions", f"{betting.get('tx_count', 0)} withdrawals", "Flags > 5 tx"],
        ["Debt Servicing (DSR)", f"{debt.get('dsr_pct', 0):.1f}% of monthly inc", debt.get("risk_level", "HEALTHY")],
        ["Total Debt / Loan Repayments", f"KES {debt.get('total_paid', 0):,.2f} ({debt.get('tx_count', 0)} tx)", "Microloans / Overdrafts"],
        ["Fuliza Overdraft Count", f"{debt.get('fuliza_count', 0)} deductions", "< 5 Normal"],
        ["Fuliza Overdraft Amount", f"KES {debt.get('fuliza_total', 0):,.2f}", "Overdraft Total"],
        ["Same-Day Re-Borrow Days", f"{data.get('same_day_reborrow_days', 0)}", "0 Preferred"],
        ["Months in Deficit", f"{data.get('deficit_months_count', 0)} of {data.get('months_analyzed', 0)}", "0 Preferred"],
        ["Overall Risk Score", f"{data.get('risk_score', 0)} / 100", "> 70 Safe"],
    ]

    prof_tbl = _make_section_table(profile_data, colors.HexColor("#00843D"), [1.6 * inch, 1.1 * inch, 0.9 * inch])
    risk_tbl = _make_section_table(risk_data, colors.HexColor("#E21836"), [1.5 * inch, 1.2 * inch, 0.9 * inch])

    two_col_table = Table([[prof_tbl, risk_tbl]], colWidths=[3.7 * inch, 3.6 * inch])
    two_col_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(two_col_table)
    story.append(Spacer(1, 0.1 * inch))

    # 4. Why this score?
    score_breakdown = data.get("score_breakdown") or []
    if score_breakdown:
        story.append(Paragraph("<b>Why This Score? (Underwriting Penalties Applied)</b>", section_title))
        sb_rows = [["Factor", "Impact", "Detail"]]
        for item in score_breakdown:
            sb_rows.append([
                str(item.get("factor", "")),
                f"{item.get('impact', 0):+d} pts",
                str(item.get("detail", "")),
            ])
        sb_tbl = _make_section_table(sb_rows, colors.HexColor("#7c2d12"), [2.4 * inch, 0.9 * inch, 2.9 * inch])
        sb_tbl.setStyle(TableStyle([
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("TEXTCOLOR", (1, 1), (1, -1), colors.HexColor("#E21836")),
            ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
        ]))
        story.append(sb_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # 5. Inflow breakdown (true income composition)
    inflow_breakdown = data.get("inflow_breakdown") or []
    if inflow_breakdown:
        story.append(Paragraph("<b>Income Composition (Loan Disbursements Excluded)</b>", section_title))
        ib_rows = [["Inflow Category", "Total (KES)", "Transactions"]]
        total_true = sum(item.get("total", 0) for item in inflow_breakdown) or 1
        for item in inflow_breakdown:
            cat = str(item.get("category", "")).replace("_", " ").title()
            ib_rows.append([
                cat,
                f"{item.get('total', 0):,.2f}",
                f"{item.get('tx_count', 0)} ({item.get('total', 0) / total_true * 100:.1f}%)",
            ])
        ib_tbl = _make_section_table(ib_rows, colors.HexColor("#0f766e"), [2.2 * inch, 1.8 * inch, 2.2 * inch])
        ib_tbl.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story.append(ib_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # 6. Fuliza trend
    fuliza_trend = data.get("fuliza_trend") or []
    has_fuliza = any(item.get("count", 0) > 0 for item in fuliza_trend)
    if has_fuliza:
        story.append(Paragraph("<b>Fuliza Usage Trend</b>", section_title))
        fz_rows = [["Month", "Fuliza Deductions", "Total Amount (KES)"]]
        for item in fuliza_trend:
            fz_rows.append([
                str(item.get("month", "")),
                str(item.get("count", 0)),
                f"{item.get('total', 0):,.2f}",
            ])
        fz_tbl = _make_section_table(fz_rows, colors.HexColor("#b45309"), [1.7 * inch, 1.8 * inch, 1.8 * inch])
        fz_tbl.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story.append(fz_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # 7. Monthly chart
    story.append(Paragraph("<b>Monthly Cash Flow Trend (Inflow vs. Outflow)</b>", section_title))
    chart_drawing = _create_monthly_chart(data.get("monthly_history", []))
    if chart_drawing:
        story.append(chart_drawing)
        story.append(Spacer(1, 0.08 * inch))

    # 8. Historical monthly breakdown
    story.append(Paragraph("<b>Historical Monthly Breakdown</b>", section_title))
    hist_headers = ["Month", "Income (KES)", "Outflow (KES)", "Net Cash Flow (KES)", "Status"]
    hist_rows = [hist_headers]
    for item in data.get("monthly_history", []):
        hist_rows.append([
            item["month"],
            f"{item['income']:,.2f}",
            f"{item['outflow']:,.2f}",
            f"{item['net']:,.2f}",
            item["status"],
        ])
    hist_tbl = Table(hist_rows, colWidths=[1.3 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch, 1.3 * inch])
    hist_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#064E3B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (1, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(hist_tbl)
    story.append(Spacer(1, 0.1 * inch))

    # 9. Loan options
    loan_options = data.get("loan_options") or {}
    if loan_options:
        story.append(Paragraph("<b>Loan Options (Based on Recommended Monthly Installment)</b>", section_title))
        lo_rows = [["Term", "Principal (KES)", "Monthly Installment (KES)"]]
        monthly = data.get("max_monthly_repayment_kes", 0)
        for term, principal in loan_options.items():
            label = term.replace("_", " ").title()
            lo_rows.append([
                label,
                f"{principal:,.2f}",
                f"{monthly:,.2f}",
            ])
        lo_tbl = _make_section_table(lo_rows, colors.HexColor("#1e40af"), [1.5 * inch, 2.4 * inch, 2.4 * inch])
        lo_tbl.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        story.append(lo_tbl)
        story.append(Spacer(1, 0.1 * inch))

    # 10. Disclaimer
    story.append(
        Paragraph(
            "<b>Underwriting Methodology & Compliance Note:</b> This assessment uses algorithmically verified "
            "mobile money transaction histories. Loan disbursements and reversals have been excluded from income "
            "to avoid overstating repayment capacity. The Stability Score reflects income volatility "
            "(Coefficient of Variation) computed on full months only. Debt obligations are cross-referenced "
            "against known Kenyan digital lenders and overdraft services. This report is intended for credit "
            "evaluators and should be coupled with standard KYC and CRB reporting.",
            body_style,
        )
    )

    doc.build(story)