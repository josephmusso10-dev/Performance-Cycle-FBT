"""
Continuously validate recommendations whenever the CSV file changes.

Usage:
  python3 watch_validate_recommendations.py
  python3 watch_validate_recommendations.py --csv product_recommendations.csv --interval 1.0 --settle 0.8
"""

import argparse
import time
from datetime import datetime
from pathlib import Path

from validate_recommendations import validate_csv


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def file_signature(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def run_validation(
    csv_path: Path,
    max_output: int,
    strict_compatibility: bool,
    compatibility_proofs: Path,
    allow_heuristic_fit: bool,
) -> int:
    errors, warnings = validate_csv(
        csv_path,
        strict_compatibility=strict_compatibility,
        compatibility_proofs_path=compatibility_proofs,
        allow_heuristic_fit=allow_heuristic_fit,
    )
    print(f"\n[{now()}] Checked: {csv_path}")
    print(f"[{now()}] Errors: {len(errors)} | Warnings: {len(warnings)}")

    if errors:
        print(f"[{now()}] Top errors:")
        for item in errors[:max_output]:
            print(f"- {item}")
        if len(errors) > max_output:
            print(f"... and {len(errors) - max_output} more errors")

    if warnings:
        print(f"[{now()}] Top warnings:")
        for item in warnings[:max_output]:
            print(f"- {item}")
        if len(warnings) > max_output:
            print(f"... and {len(warnings) - max_output} more warnings")

    if errors:
        print(f"[{now()}] Validation failed.")
        return 1

    print(f"[{now()}] Validation passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch recommendation CSV and validate on every update.")
    parser.add_argument(
        "--csv",
        default="product_recommendations.csv",
        help="Path to recommendations CSV (default: product_recommendations.csv)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=0.75,
        help="Wait this long after a detected change before validating (default: 0.75)",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=20,
        help="Max errors/warnings to print per section (default: 20)",
    )
    parser.add_argument(
        "--strict-compatibility",
        action="store_true",
        help="Require source-backed proof for fit-sensitive helmet accessory recommendations",
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
        help="In strict mode, treat brand/model overlap as warning instead of error when proof is missing",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    proofs_path = Path(args.compatibility_proofs)
    print(f"[{now()}] Watching for updates: {csv_path}")
    print(f"[{now()}] Press Ctrl+C to stop.")

    try:
        if csv_path.exists():
            run_validation(
                csv_path,
                args.max_output,
                args.strict_compatibility,
                proofs_path,
                args.allow_heuristic_fit,
            )
        else:
            print(f"[{now()}] CSV not found yet: {csv_path}")

        previous = file_signature(csv_path)
        pending_change_since = None

        while True:
            current = file_signature(csv_path)
            if current != previous:
                pending_change_since = time.time()
                previous = current

            if pending_change_since is not None:
                if time.time() - pending_change_since >= args.settle:
                    if csv_path.exists():
                        print(f"[{now()}] Change detected, running validation...")
                        run_validation(
                            csv_path,
                            args.max_output,
                            args.strict_compatibility,
                            proofs_path,
                            args.allow_heuristic_fit,
                        )
                    else:
                        print(f"[{now()}] Change detected but CSV is missing: {csv_path}")
                    pending_change_since = None

            time.sleep(max(args.interval, 0.1))
    except KeyboardInterrupt:
        print(f"\n[{now()}] Watch stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
