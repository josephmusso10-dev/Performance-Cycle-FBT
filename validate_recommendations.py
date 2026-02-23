"""
Recommendation CSV validator.

Validates that:
- recommendations are complementary for core apparel/helmet product types,
- rows are structurally valid,
- fit-sensitive helmet accessories are compatibility-safe.

Optional strict mode enforces source-backed compatibility proof for
fit-sensitive helmet accessory recommendations only.
"""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


TYPE_RULES = [
    (
        "helmet_accessory",
        [
            "visor",
            "face shield",
            "faceshield",
            "shield",
            "pinlock",
            "cheek pad",
            "cheek-pad",
            "cheekpad",
            "cheekpads",
        ],
    ),
    ("helmet", ["helmet"]),
    ("jacket", ["jacket", "coat", "parka"]),
    ("pants", ["pant", "trouser", "bibs"]),
    ("gloves", ["glove", "gauntlet"]),
    ("boots", ["boot", "shoe"]),
    ("backpack", ["backpack", "bag", "pack", "luggage"]),
    ("communication", ["communication", "intercom", "bluetooth", "headset", "sena", "cardo", "schuberth-sc2"]),
    ("tire", ["tire", "tyre", "wheel"]),
    ("air_filter", ["air filter", "air-filter", "filter"]),
    ("oil", ["oil", "lubricant", "lube", "fork oil", "transmission oil"]),
    ("brake", ["brake", "brake pad", "rotor"]),
    ("chain", ["chain", "sprocket", "degreaser", "chain lube", "chain wax"]),
    ("protection", ["protector", "armor", "armour", "chest", "back protector"]),
]

COMPLEMENTARY_TYPES = {
    "pants": {"jacket", "gloves", "boots", "protection", "backpack"},
    "jacket": {"pants", "gloves", "boots", "protection", "helmet"},
    "gloves": {"jacket", "pants", "boots", "helmet"},
    "boots": {"pants", "jacket", "gloves", "helmet"},
    "helmet": {"helmet_accessory", "communication", "backpack", "jacket", "gloves"},
    "helmet_accessory": {"helmet", "communication", "backpack"},
    "communication": {"helmet", "backpack"},
    "tire": {"brake", "chain", "oil"},
    "air_filter": {"oil", "chain", "brake"},
    "oil": {"air_filter", "chain", "brake"},
    "chain": {"oil", "brake", "air_filter"},
    "brake": {"tire", "chain", "oil"},
    "backpack": {"helmet", "jacket", "gloves"},
    "protection": {"jacket", "pants", "gloves", "boots"},
}

CORE_COMPLEMENTARY_TYPES = {"pants", "jacket", "gloves", "boots", "helmet"}

KNOWN_HELMET_BRANDS = {
    "shoei",
    "arai",
    "agv",
    "hjc",
    "bell",
    "scorpion",
    "ls2",
    "icon",
    "sedici",
    "shark",
    "schuberth",
    "suomy",
    "simpson",
    "nolan",
    "xlite",
    "caberg",
    "klim",
}

FIT_SENSITIVE_ACCESSORY_TERMS = {
    "visor",
    "shield",
    "faceshield",
    "face-shield",
    "pinlock",
    "cheek",
    "cheekpad",
    "cheek-pad",
    "peak",
    "spoiler",
}

MODEL_STOPWORDS = {
    "helmet",
    "visor",
    "shield",
    "pinlock",
    "face",
    "clear",
    "dark",
    "smoke",
    "tinted",
    "replacement",
    "motorcycle",
    "racing",
    "race",
    "edition",
    "with",
    "for",
    "the",
    "and",
    "kit",
    "pack",
    "single",
    "dual",
    "v",
    "pro",
    "plus",
    "series",
}


def normalize_text(value: str) -> str:
    return (value or "").strip().lower().replace("-", " ")


def slug_tokens(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def detect_type(product_slug: str) -> str:
    text = normalize_text(product_slug)
    for type_name, keywords in TYPE_RULES:
        if any(keyword in text for keyword in keywords):
            return type_name
    return "unknown"


def extract_helmet_identity(slug: str) -> Tuple[Set[str], Set[str]]:
    tokens = slug_tokens(slug)
    brands = {token for token in tokens if token in KNOWN_HELMET_BRANDS}
    model_tokens = {
        token
        for token in tokens
        if len(token) >= 2
        and token not in KNOWN_HELMET_BRANDS
        and token not in MODEL_STOPWORDS
    }
    return brands, model_tokens


def is_fit_sensitive_helmet_accessory(slug: str) -> bool:
    text = (slug or "").lower()
    return any(term in text for term in FIT_SENSITIVE_ACCESSORY_TERMS)


def parse_bool(value: str) -> bool:
    text = (value or "").strip().lower()
    return text in {"true", "yes", "y", "1", "verified"}


def load_compatibility_proofs(proofs_path: Optional[Path]) -> Tuple[Dict[Tuple[str, str], dict], List[str]]:
    proofs: Dict[Tuple[str, str], dict] = {}
    issues: List[str] = []
    if proofs_path is None:
        return proofs, issues

    if not proofs_path.exists():
        issues.append(f"Compatibility proofs file not found: {proofs_path}")
        return proofs, issues

    required = {
        "Product ID",
        "Recommended Product ID",
        "Compatibility Verified",
        "Compatibility Source",
    }
    with proofs_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or [])
        missing = required - header
        if missing:
            issues.append(
                f"Compatibility proofs file missing required columns: {', '.join(sorted(missing))}"
            )
            return proofs, issues

        for row_num, row in enumerate(reader, start=2):
            product_id = (row.get("Product ID") or "").strip()
            rec_id = (row.get("Recommended Product ID") or "").strip()
            if not product_id or not rec_id:
                issues.append(
                    f"Proofs row {row_num}: missing Product ID or Recommended Product ID"
                )
                continue

            source = (row.get("Compatibility Source") or "").strip()
            verified = parse_bool(row.get("Compatibility Verified") or "")
            notes = (row.get("Compatibility Notes") or "").strip()
            key = (product_id, rec_id)
            proofs[key] = {"verified": verified, "source": source, "notes": notes}

    return proofs, issues


def validate_csv(
    csv_path: Path,
    strict_compatibility: bool = False,
    compatibility_proofs_path: Optional[Path] = None,
    allow_heuristic_fit: bool = True,
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    required_columns = {"Product ID", "Recommended Product ID"}
    seen_by_product: Dict[str, Set[str]] = defaultdict(set)
    compatibility_proofs, proof_issues = load_compatibility_proofs(compatibility_proofs_path)
    if strict_compatibility:
        errors.extend(proof_issues)
    else:
        warnings.extend(proof_issues)

    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or [])
        missing = required_columns - header
        if missing:
            errors.append(f"Missing required columns: {', '.join(sorted(missing))}")
            return errors, warnings

        for row_num, row in enumerate(reader, start=2):
            product_id = (row.get("Product ID") or "").strip()
            rec_id = (row.get("Recommended Product ID") or "").strip()
            is_category_rule = product_id.startswith("[") and "]" in product_id

            if not product_id or not rec_id:
                errors.append(f"Row {row_num}: missing Product ID or Recommended Product ID")
                continue

            if product_id == rec_id:
                errors.append(f"Row {row_num}: self-recommendation is not allowed ({product_id})")

            if rec_id in seen_by_product[product_id]:
                errors.append(f"Row {row_num}: duplicate recommendation for '{product_id}' -> '{rec_id}'")
            seen_by_product[product_id].add(rec_id)

            source_type = detect_type(product_id)
            rec_type = detect_type(rec_id)

            if not is_category_rule and source_type != "unknown" and rec_type != "unknown":
                if source_type == rec_type and source_type in CORE_COMPLEMENTARY_TYPES:
                    errors.append(
                        f"Row {row_num}: non-complementary recommendation ({source_type} -> {rec_type}) "
                        f"for '{product_id}' -> '{rec_id}'"
                    )

                allowed = COMPLEMENTARY_TYPES.get(source_type)
                if source_type in CORE_COMPLEMENTARY_TYPES and allowed and rec_type not in allowed:
                    warnings.append(
                        f"Row {row_num}: unusual pair ({source_type} -> {rec_type}) "
                        f"for '{product_id}' -> '{rec_id}'"
                    )

            # Fit-sensitive helmet compatibility check.
            if not is_category_rule and source_type == "helmet" and is_fit_sensitive_helmet_accessory(rec_id):
                src_brands, src_models = extract_helmet_identity(product_id)
                rec_brands, rec_models = extract_helmet_identity(rec_id)
                pair_key = (product_id, rec_id)
                proof = compatibility_proofs.get(pair_key)
                has_verified_source = (
                    bool(proof)
                    and proof.get("verified", False)
                    and bool((proof.get("source") or "").strip())
                )

                if src_brands and rec_brands and src_brands.isdisjoint(rec_brands):
                    errors.append(
                        f"Row {row_num}: helmet brand mismatch for fit-sensitive accessory "
                        f"('{product_id}' -> '{rec_id}')"
                    )

                rec_tokens = set(slug_tokens(rec_id))
                has_for_marker = "for" in rec_tokens
                model_overlap = bool(src_models & rec_models)
                brand_overlap = bool(src_brands & rec_brands)
                heuristic_fit_ok = brand_overlap or model_overlap

                if has_for_marker and not heuristic_fit_ok:
                    warnings.append(
                        f"Row {row_num}: accessory appears model-specific but no helmet model match was found "
                        f"('{product_id}' -> '{rec_id}')"
                    )

                if strict_compatibility:
                    if not has_verified_source:
                        if allow_heuristic_fit and heuristic_fit_ok:
                            warnings.append(
                                f"Row {row_num}: no source proof entry, but heuristic fit looks plausible "
                                f"('{product_id}' -> '{rec_id}')"
                            )
                        else:
                            errors.append(
                                f"Row {row_num}: missing verified compatibility source for fit-sensitive accessory "
                                f"('{product_id}' -> '{rec_id}')"
                            )
                # In non-strict mode, missing source proof is informational only.

    return errors, warnings


def categorize_issue(message: str) -> str:
    text = (message or "").lower()
    if "helmet brand mismatch" in text:
        return "definite mismatch"
    if "missing verified compatibility source" in text:
        return "missing proof"
    if "no source proof entry, but heuristic fit looks plausible" in text:
        return "heuristic uncertain"
    if "no helmet model match was found" in text:
        return "heuristic uncertain"
    return "other"


def print_category_summary(errors: List[str], warnings: List[str], max_output: int) -> None:
    categories = {
        "definite mismatch": {"errors": [], "warnings": []},
        "missing proof": {"errors": [], "warnings": []},
        "heuristic uncertain": {"errors": [], "warnings": []},
        "other": {"errors": [], "warnings": []},
    }

    for item in errors:
        categories[categorize_issue(item)]["errors"].append(item)
    for item in warnings:
        categories[categorize_issue(item)]["warnings"].append(item)

    print("\nIssue categories:")
    for name in ("definite mismatch", "missing proof", "heuristic uncertain", "other"):
        err_count = len(categories[name]["errors"])
        warn_count = len(categories[name]["warnings"])
        total = err_count + warn_count
        if total == 0:
            continue
        print(f"- {name}: {total} (errors={err_count}, warnings={warn_count})")

    for name in ("definite mismatch", "missing proof", "heuristic uncertain"):
        samples = categories[name]["errors"] + categories[name]["warnings"]
        if not samples:
            continue
        print(f"\nTop {name} issues:")
        for item in samples[:max_output]:
            print(f"- {item}")
        if len(samples) > max_output:
            print(f"... and {len(samples) - max_output} more")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate recommendation CSV quality and compatibility.")
    parser.add_argument(
        "--csv",
        default="product_recommendations.csv",
        help="Path to recommendations CSV (default: product_recommendations.csv)",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=50,
        help="Max errors/warnings to print per section (default: 50)",
    )
    parser.add_argument(
        "--strict-compatibility",
        action="store_true",
        help="Require verified source-backed compatibility for fit-sensitive helmet accessories",
    )
    parser.add_argument(
        "--compatibility-proofs",
        default="compatibility_proofs.csv",
        help="Path to compatibility proofs CSV (default: compatibility_proofs.csv)",
    )
    parser.add_argument(
        "--allow-heuristic-fit",
        action="store_true",
        default=False,
        help="In strict mode, allow brand/model heuristic overlap to downgrade missing proof to warning",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        return 2

    proofs_path = Path(args.compatibility_proofs) if args.compatibility_proofs else None
    errors, warnings = validate_csv(
        csv_path,
        strict_compatibility=args.strict_compatibility,
        compatibility_proofs_path=proofs_path,
        allow_heuristic_fit=args.allow_heuristic_fit,
    )

    print(f"Checked: {csv_path}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    if args.strict_compatibility:
        print(f"Compatibility proofs: {proofs_path}")
    print_category_summary(errors, warnings, args.max_output)

    if errors:
        print("\nTop errors:")
        for item in errors[: args.max_output]:
            print(f"- {item}")
        if len(errors) > args.max_output:
            print(f"... and {len(errors) - args.max_output} more errors")

    if warnings:
        print("\nTop warnings:")
        for item in warnings[: args.max_output]:
            print(f"- {item}")
        if len(warnings) > args.max_output:
            print(f"... and {len(warnings) - args.max_output} more warnings")

    if errors:
        print("\nValidation failed.")
        return 1

    print("\nValidation passed (no blocking issues).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
