"""
Auto-fix recommendation rows classified as definite mismatch.

Current definite mismatch rule:
- helmet -> fit-sensitive helmet accessory where accessory brand conflicts with helmet brand.

This script replaces only those rows with a best-effort compatible alternative.
"""

import argparse
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from validate_recommendations import (
    COMPLEMENTARY_TYPES,
    detect_type,
    extract_helmet_identity,
    is_fit_sensitive_helmet_accessory,
)


def is_definite_mismatch(product_id: str, rec_id: str) -> bool:
    source_type = detect_type(product_id)
    if source_type != "helmet":
        return False
    if not is_fit_sensitive_helmet_accessory(rec_id):
        return False

    src_brands, _ = extract_helmet_identity(product_id)
    rec_brands, _ = extract_helmet_identity(rec_id)
    return bool(src_brands and rec_brands and src_brands.isdisjoint(rec_brands))


def load_verified_proofs(proofs_path: Optional[Path]) -> Dict[str, Set[str]]:
    by_product: Dict[str, Set[str]] = defaultdict(set)
    if not proofs_path or not proofs_path.exists():
        return by_product

    with proofs_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            product_id = (row.get("Product ID") or "").strip()
            rec_id = (row.get("Recommended Product ID") or "").strip()
            verified = (row.get("Compatibility Verified") or "").strip().lower()
            source = (row.get("Compatibility Source") or "").strip()
            if not product_id or not rec_id:
                continue
            if verified in {"yes", "y", "true", "1", "verified"} and source:
                by_product[product_id].add(rec_id)
    return by_product


def score_candidate(
    source_product_id: str,
    original_rec_id: str,
    candidate_id: str,
    source_existing_recs: Set[str],
) -> int:
    if candidate_id == source_product_id:
        return -10_000
    if candidate_id in source_existing_recs:
        return -9_000
    if is_definite_mismatch(source_product_id, candidate_id):
        return -8_000

    source_type = detect_type(source_product_id)
    original_type = detect_type(original_rec_id)
    candidate_type = detect_type(candidate_id)
    allowed = COMPLEMENTARY_TYPES.get(source_type, set())
    if allowed and candidate_type not in allowed:
        return -7_000

    src_brands, src_models = extract_helmet_identity(source_product_id)
    cand_brands, cand_models = extract_helmet_identity(candidate_id)
    brand_overlap = bool(src_brands & cand_brands)
    model_overlap = bool(src_models & cand_models)

    score = 0
    if candidate_type == original_type:
        score += 80
    if candidate_type == "helmet_accessory":
        score += 30
    if brand_overlap:
        score += 70
    if model_overlap:
        score += 60
    if is_fit_sensitive_helmet_accessory(candidate_id):
        score += 10
    if "for" in candidate_id.lower() and (brand_overlap or model_overlap):
        score += 10
    return score


def pick_replacement(
    source_product_id: str,
    original_rec_id: str,
    source_existing_recs: Set[str],
    verified_candidates: Set[str],
    global_candidates: List[str],
) -> Optional[str]:
    # Prefer verified source-backed candidates first.
    ranked_verified = sorted(
        verified_candidates,
        key=lambda c: score_candidate(source_product_id, original_rec_id, c, source_existing_recs),
        reverse=True,
    )
    for candidate in ranked_verified:
        if score_candidate(source_product_id, original_rec_id, candidate, source_existing_recs) > 0:
            return candidate

    # Fallback to best heuristic candidate in global pool.
    best = None
    best_score = -10_000
    for candidate in global_candidates:
        score = score_candidate(source_product_id, original_rec_id, candidate, source_existing_recs)
        if score > best_score:
            best_score = score
            best = candidate
    if best and best_score > 0:
        return best
    return None


def read_rows(csv_path: Path) -> Tuple[List[dict], List[str]]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def write_rows(csv_path: Path, rows: List[dict], fieldnames: List[str]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-fix definite mismatch recommendation rows.")
    parser.add_argument("--csv", default="product_recommendations.csv", help="Input recommendations CSV path")
    parser.add_argument(
        "--compatibility-proofs",
        default="compatibility_proofs.csv",
        help="Optional compatibility proofs CSV path (used to prefer verified replacements)",
    )
    parser.add_argument(
        "--out",
        default="product_recommendations.autofixed.csv",
        help="Output CSV path for fixed recommendations (default: product_recommendations.autofixed.csv)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite input CSV in place and create timestamped .bak backup",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write files; only print what would be changed",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=20,
        help="Max changed/unresolved examples to print (default: 20)",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        return 2

    proofs_path = Path(args.compatibility_proofs) if args.compatibility_proofs else None
    verified_by_product = load_verified_proofs(proofs_path)
    rows, fieldnames = read_rows(csv_path)
    if not fieldnames:
        print("ERROR: CSV has no header.")
        return 2

    product_recs: Dict[str, Set[str]] = defaultdict(set)
    global_candidates_set: Set[str] = set()
    for row in rows:
        pid = (row.get("Product ID") or "").strip()
        rid = (row.get("Recommended Product ID") or "").strip()
        if not pid or not rid:
            continue
        product_recs[pid].add(rid)
        global_candidates_set.add(rid)

    global_candidates = sorted(global_candidates_set)
    changes: List[Tuple[int, str, str, str]] = []
    unresolved: List[Tuple[int, str, str]] = []

    for idx, row in enumerate(rows):
        row_num = idx + 2
        product_id = (row.get("Product ID") or "").strip()
        rec_id = (row.get("Recommended Product ID") or "").strip()
        if not product_id or not rec_id:
            continue
        if product_id.startswith("[") and "]" in product_id:
            continue
        if not is_definite_mismatch(product_id, rec_id):
            continue

        source_existing = set(product_recs.get(product_id, set()))
        source_existing.discard(rec_id)
        replacement = pick_replacement(
            source_product_id=product_id,
            original_rec_id=rec_id,
            source_existing_recs=source_existing,
            verified_candidates=verified_by_product.get(product_id, set()),
            global_candidates=global_candidates,
        )
        if not replacement:
            unresolved.append((row_num, product_id, rec_id))
            continue

        row["Recommended Product ID"] = replacement
        product_recs[product_id].discard(rec_id)
        product_recs[product_id].add(replacement)
        changes.append((row_num, product_id, rec_id, replacement))

    print(f"Scanned rows: {len(rows)}")
    print(f"Definite mismatches fixed: {len(changes)}")
    print(f"Definite mismatches unresolved: {len(unresolved)}")

    if changes:
        print("\nTop replacements:")
        for row_num, pid, old, new in changes[: args.max_output]:
            print(f"- Row {row_num}: '{pid}' -> '{old}' replaced with '{new}'")
        if len(changes) > args.max_output:
            print(f"... and {len(changes) - args.max_output} more replacements")

    if unresolved:
        print("\nTop unresolved rows:")
        for row_num, pid, rec in unresolved[: args.max_output]:
            print(f"- Row {row_num}: '{pid}' -> '{rec}'")
        if len(unresolved) > args.max_output:
            print(f"... and {len(unresolved) - args.max_output} more unresolved rows")

    if args.dry_run:
        print("\nDry run complete. No files written.")
        return 0

    if args.in_place:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = csv_path.with_suffix(csv_path.suffix + f".{timestamp}.bak")
        backup_path.write_bytes(csv_path.read_bytes())
        write_rows(csv_path, rows, fieldnames)
        print(f"\nWrote in-place updates to: {csv_path}")
        print(f"Backup created: {backup_path}")
    else:
        out_path = Path(args.out)
        write_rows(out_path, rows, fieldnames)
        print(f"\nWrote fixed CSV to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
