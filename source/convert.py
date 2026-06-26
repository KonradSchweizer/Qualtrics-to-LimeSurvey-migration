#!/usr/bin/env python3
"""
convert.py — CLI entry point for the QSF → LSS conversion pipeline.

Usage:
    python convert.py survey.qsf                    # Convert to survey.lss
    python convert.py survey.qsf -o output.lss      # Convert to specific output
    python convert.py survey.qsf --inspect           # Convert + run inspector
    python convert.py folder/ -o outdir/             # Batch convert all QSF files

No external dependencies — stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qsf_to_lss import convert_qsf_to_lss


def find_qsf_files(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() == ".qsf":
        return [target]
    if target.is_dir():
        return sorted(target.rglob("*.qsf"))
    return []


def run_inspector(qsf_path: Path) -> None:
    """Run the QSF inspector on a file and print results."""
    try:
        from qsf_inspector import inspect_one, aggregate, print_console_summary
        report = inspect_one(qsf_path)
        agg = aggregate([report])
        print_console_summary([report], agg)
    except Exception as exc:
        print(f"  Inspector error: {exc}", file=sys.stderr)


def convert_one(qsf_path: Path, out_path: Path, inspect: bool = False) -> bool:
    """Convert a single QSF file. Returns True on success."""
    print(f"Converting: {qsf_path.name}")

    if inspect:
        run_inspector(qsf_path)
        print()

    try:
        lss_xml, warnings = convert_qsf_to_lss(qsf_path)
    except Exception as exc:
        print(f"  FAILED: {exc}", file=sys.stderr)
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(lss_xml, encoding="utf-8")
    print(f"  -> {out_path}")

    if warnings:
        print(f"  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"    - {w}")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Qualtrics .qsf files to LimeSurvey .lss files."
    )
    parser.add_argument(
        "input", type=Path,
        help="Path to a .qsf file or folder containing .qsf files"
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output .lss file path (single file) or directory (batch mode)"
    )
    parser.add_argument(
        "--inspect", action="store_true",
        help="Run the QSF inspector before conversion"
    )
    args = parser.parse_args()

    files = find_qsf_files(args.input)
    if not files:
        print(f"No .qsf files found at {args.input}", file=sys.stderr)
        return 1

    successes = 0

    if len(files) == 1:
        # Single file mode
        out = args.output or files[0].with_suffix(".lss")
        if convert_one(files[0], out, args.inspect):
            successes += 1
    else:
        # Batch mode
        outdir = args.output or files[0].parent / "lss_output"
        for f in files:
            out = outdir / f.with_suffix(".lss").name
            if convert_one(f, out, args.inspect):
                successes += 1

    print(f"\nDone: {successes}/{len(files)} file(s) converted successfully.")

    if successes < len(files):
        print("Some files had errors. Review warnings above.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
