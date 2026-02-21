"""
Creates CSV/Excel of product recommendations for Performance Cycle.
Run: python create_recommendations_excel.py
Output: product_recommendations.csv (or .xlsx if openpyxl available)
"""

import csv
import sys
from pathlib import Path

def create_csv():
    """Create CSV with explicit mappings + category rules."""
    from product_recommendations import RECOMMENDATIONS, CATEGORY_RULES
    out = Path(__file__).parent / "product_recommendations.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Product ID", "Recommended Product ID", "Label", "Type"])
        # 1. Explicit product mappings
        for product_id, recs in sorted(RECOMMENDATIONS.items()):
            for rec in recs:
                w.writerow([product_id, rec.get("id", ""), rec.get("label", ""), "Explicit"])
        # 2. Category fallback rules (applies to any product matching keywords)
        for keywords, recs in CATEGORY_RULES:
            kw_str = " | ".join(keywords)
            for rec in recs:
                w.writerow([f"[{kw_str}] (any product containing)", rec.get("id", ""), rec.get("label", ""), "Category"])
    return out

def create_xlsx():
    """Create .xlsx if openpyxl available."""
    try:
        from openpyxl import Workbook
        from product_recommendations import RECOMMENDATIONS, CATEGORY_RULES
        wb = Workbook()
        # Sheet 1: Explicit mappings
        ws1 = wb.active
        ws1.title = "Product Recommendations"
        ws1.append(["Product ID", "Recommended Product ID", "Label", "Type"])
        for product_id, recs in sorted(RECOMMENDATIONS.items()):
            for rec in recs:
                ws1.append([product_id, rec.get("id", ""), rec.get("label", ""), "Explicit"])
        for col in ws1.columns:
            max_len = max(len(str(c.value) or "") for c in col)
            ws1.column_dimensions[col[0].column_letter].width = min(max_len + 2, 80)
        # Sheet 2: Category rules
        ws2 = wb.create_sheet("Category Rules (Fallback)")
        ws2.append(["Keyword(s)", "Recommended Product ID", "Label"])
        ws2.append(["", "", "Products matching these keywords get these recommendations"])
        for keywords, recs in CATEGORY_RULES:
            kw_str = ", ".join(keywords)
            for rec in recs:
                ws2.append([kw_str, rec.get("id", ""), rec.get("label", "")])
        for col in ws2.columns:
            max_len = max(len(str(c.value) or "") for c in col)
            ws2.column_dimensions[col[0].column_letter].width = min(max_len + 2, 80)
        out = Path(__file__).parent / "product_recommendations.xlsx"
        wb.save(out)
        return out
    except ImportError:
        return None

if __name__ == "__main__":
    path = create_xlsx()
    if path:
        print(f"Created {path}")
    else:
        path = create_csv()
        print(f"Created {path}")
        print("To create .xlsx: pip install openpyxl")
