"""The four quarters of TD_P&L_QoQ_Rev.xlsx (sheet 'P&L QoQ'), entered exactly as in the workbook.

Inputs only - every other line is calculated by masters/pnl.py with the workbook's formulas:
COGS 70% of Net Revenue, Payment Gateway 1% of Gross Revenue, Loyalty (Gross x 0.5%) / 2 = 0.25% of Gross Revenue.
Misc: Q3 FY25-26 = 57,000 x 3 (cell C17); Q4 FY25-26 and Q1 FY26-27 = Q2's 1,00,000 (cells E17 / G17 = B17).
"""
from decimal import Decimal

from django.db import migrations

SRC = "From TD_P&L_QoQ_Rev.xlsx"
QUARTERS = [
    # start, gross revenue, returns, tech / platform, manpower & operating, misc, note
    ("2025-07-01", "38215415", "261196", "800000", "600000", "100000", SRC),
    ("2025-10-01", "52696650", "433164", "800000", "600000", "171000", f"{SRC}. Misc = 57,000 x 3."),
    ("2026-01-01", "64317241", "388160.40", "800000", "600000", "100000", SRC),
    ("2026-04-01", "74616928", "1147799", "800000", "600000", "100000", SRC),
]


def forwards(apps, schema_editor):
    PnlQuarter = apps.get_model("masters", "PnlQuarter")
    for start, gross, ret, tech, man, misc, note in QUARTERS:
        PnlQuarter.objects.update_or_create(quarter_start=start, defaults=dict(
            gross_revenue=Decimal(gross), returns=Decimal(ret), cogs_pct=Decimal("70"), pg_pct=Decimal("1"),
            loyalty_pct=Decimal("0.25"), tech_platform_cost=Decimal(tech), manpower_operating_cost=Decimal(man),
            misc_expense=Decimal(misc), notes=note, updated_by="TD_P&L_QoQ_Rev.xlsx"))


def backwards(apps, schema_editor):
    apps.get_model("masters", "PnlQuarter").objects.filter(quarter_start__in=[q[0] for q in QUARTERS]).delete()


class Migration(migrations.Migration):
    dependencies = [("masters", "0002_pnl")]
    operations = [migrations.RunPython(forwards, backwards)]
