#!/usr/bin/env python3
"""
app.py — Standalone entry point for the QualtricsToLime .exe distribution.

Place .qsf files in the 'input' folder, run the exe, get .lss files in 'output'.
Shows a report of input (QSF analysis), output (conversion results), and verification.
Saves the full report as a text document in the output folder.
"""

import sys
import os
import json
from datetime import datetime
from pathlib import Path
from collections import Counter
from xml.etree.ElementTree import parse as parse_xml

# When running as a PyInstaller bundle, work relative to the .exe location.
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

sys.path.insert(0, str(APP_DIR))

from qsf_to_lss import convert_qsf_to_lss, TYPE_MAP
from qsf_inspector import inspect_one

HEADER = "=" * 64
DIVIDER = "-" * 64
THIN = "." * 64


# ---------------------------------------------------------------------------
# Report writer: prints to console and collects lines for the document
# ---------------------------------------------------------------------------
class ReportWriter:
    """Dual output: prints to console and collects lines for file output."""

    def __init__(self):
        self.lines: list[str] = []

    def write(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def header(self, title: str) -> None:
        self.write()
        self.write(HEADER)
        self.write(f"  {title}")
        self.write(HEADER)

    def section(self, title: str) -> None:
        self.write()
        self.write(f"  {title}")
        self.write(f"  {DIVIDER[:len(title) + 4]}")

    def row(self, label: str, value, indent: int = 4) -> None:
        prefix = " " * indent
        self.write(f"{prefix}{label:<40s} {value}")

    def blank(self) -> None:
        self.write()

    def save(self, path: Path) -> None:
        path.write_text("\n".join(self.lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Input report
# ---------------------------------------------------------------------------
def write_input_report(w: ReportWriter, qsf_path: Path, report: dict) -> None:
    s = report["summary"]

    w.section(f"INPUT: {qsf_path.name}")

    w.row("Survey name", s.get("survey_name", "—"))
    w.row("Language", s.get("language", "—"))
    w.row("Questions", s["n_questions"])
    w.row("Blocks (question groups)", s["n_blocks"])
    if s.get("n_randomized_blocks"):
        w.row("Randomized blocks", s["n_randomized_blocks"])

    type_counts = s.get("question_types", {})
    if type_counts:
        w.blank()
        w.row("Question types", "")
        for qtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            w.row(f"  {qtype}", count, indent=6)

    features = []
    if s.get("n_questions_with_display_logic"):
        features.append(("Display logic", s["n_questions_with_display_logic"]))
    if s.get("n_questions_with_validation"):
        features.append(("Validation rules", s["n_questions_with_validation"]))
    if s.get("n_piped_text_occurrences"):
        features.append(("Piped text refs", s["n_piped_text_occurrences"]))
    if s.get("n_questions_with_javascript"):
        features.append(("Custom JavaScript", s["n_questions_with_javascript"]))
    if s.get("n_questions_with_choice_randomization"):
        features.append(("Choice randomization", s["n_questions_with_choice_randomization"]))
    if s.get("n_branches"):
        features.append(("Branch logic (flow)", s["n_branches"]))
    if s.get("n_randomizers"):
        features.append(("Randomizers (flow)", s["n_randomizers"]))
    if s.get("n_embedded_data_blocks"):
        features.append(("Embedded data blocks", s["n_embedded_data_blocks"]))

    if features:
        w.blank()
        w.row("Features detected", "")
        for label, val in features:
            w.row(f"  {label}", val, indent=6)

    warnings = []
    if s.get("n_problem_question_types"):
        warnings.append(f"{s['n_problem_question_types']} problem question type(s) (no LimeSurvey equivalent)")
    if s.get("n_unmapped_question_types"):
        warnings.append(f"{s['n_unmapped_question_types']} unmapped question type(s)")
    if s.get("n_questions_with_javascript"):
        warnings.append(f"{s['n_questions_with_javascript']} question(s) with custom JavaScript (needs review)")

    if warnings:
        w.blank()
        w.row("Warnings", "")
        for warning in warnings:
            w.write(f"        ! {warning}")

    w.row("Migration risk score", s.get("migration_risk_score", 0))


# ---------------------------------------------------------------------------
# LSS analysis
# ---------------------------------------------------------------------------
def analyse_lss(lss_path: Path) -> dict:
    try:
        tree = parse_xml(str(lss_path))
        root = tree.getroot()

        def count_rows(table_name: str) -> int:
            table = root.find(table_name)
            if table is None:
                return 0
            rows = table.find("rows")
            if rows is None:
                return 0
            return len(list(rows))

        def get_field(row, field: str) -> str:
            el = row.find(field)
            return (el.text or "") if el is not None else ""

        type_counts: Counter = Counter()
        n_mandatory = 0
        n_with_relevance = 0
        question_titles: list[str] = []
        questions_table = root.find("questions")
        if questions_table is not None:
            rows = questions_table.find("rows")
            if rows is not None:
                for row in rows:
                    qtype = get_field(row, "type")
                    if qtype:
                        type_counts[qtype] += 1
                    if get_field(row, "mandatory") == "Y":
                        n_mandatory += 1
                    relevance = get_field(row, "relevance")
                    if relevance and relevance != "1":
                        n_with_relevance += 1
                    title = get_field(row, "title")
                    if title:
                        question_titles.append(title)

        answers_per_question: Counter = Counter()
        answers_table = root.find("answers")
        if answers_table is not None:
            rows = answers_table.find("rows")
            if rows is not None:
                for row in rows:
                    qid = get_field(row, "qid")
                    if qid:
                        answers_per_question[qid] += 1

        subqs_per_question: Counter = Counter()
        subqs_table = root.find("subquestions")
        if subqs_table is not None:
            rows = subqs_table.find("rows")
            if rows is not None:
                for row in rows:
                    parent = get_field(row, "parent_qid")
                    if parent and parent != "0":
                        subqs_per_question[parent] += 1

        return {
            "groups": count_rows("groups"),
            "questions": count_rows("questions"),
            "subquestions": count_rows("subquestions"),
            "answers": count_rows("answers"),
            "question_attributes": count_rows("question_attributes"),
            "question_types": dict(type_counts),
            "n_mandatory": n_mandatory,
            "n_with_relevance": n_with_relevance,
            "question_titles": question_titles,
            "n_questions_with_answers": len(answers_per_question),
            "n_questions_with_subquestions": len(subqs_per_question),
        }
    except Exception:
        return {}


LS_TYPE_NAMES = {
    "L": "List (Radio)",
    "!": "List (Dropdown)",
    "M": "Multiple Choice",
    "S": "Short Free Text",
    "T": "Long Free Text",
    "Q": "Multiple Short Text",
    "F": "Array",
    ";": "Array (Texts)",
    "1": "Array Dual Scale",
    "R": "Ranking",
    "X": "Text Display",
    "N": "Numerical Input",
    "K": "Multiple Numerical",
}


# ---------------------------------------------------------------------------
# Output report
# ---------------------------------------------------------------------------
def write_output_report(w: ReportWriter, lss_path: Path, warnings: list[str], lss_stats: dict) -> None:
    w.section(f"OUTPUT: {lss_path.name}")

    if lss_stats:
        w.row("Question groups", lss_stats.get("groups", 0))
        w.row("Questions", lss_stats.get("questions", 0))
        w.row("Subquestions (array rows)", lss_stats.get("subquestions", 0))
        w.row("Answer options", lss_stats.get("answers", 0))
        if lss_stats.get("question_attributes"):
            w.row("Question attributes", lss_stats["question_attributes"])

        type_counts = lss_stats.get("question_types", {})
        if type_counts:
            w.blank()
            w.row("LimeSurvey question types", "")
            for code, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                name = LS_TYPE_NAMES.get(code, code)
                w.row(f"  {code} — {name}", count, indent=6)

    if warnings:
        w.blank()
        w.row("Conversion warnings", len(warnings))
        for warning in warnings:
            w.write(f"        ! {warning}")
    else:
        w.blank()
        w.row("Conversion warnings", "None")


# ---------------------------------------------------------------------------
# Checking layer: compare input (QSF) against output (LSS)
# ---------------------------------------------------------------------------
def run_checks(report: dict, lss_stats: dict, conversion_warnings: list[str]) -> list[tuple[str, str]]:
    checks: list[tuple[str, str]] = []
    s = report["summary"]
    questions = report["questions"]

    if not lss_stats:
        checks.append(("FAIL", "Could not parse LSS output for verification"))
        return checks

    # 1. Question count
    qsf_q = s["n_questions"]
    lss_q = lss_stats["questions"]

    if lss_q == qsf_q:
        checks.append(("OK", f"Question count matches: {qsf_q}"))
    elif lss_q < qsf_q:
        diff = qsf_q - lss_q
        checks.append(("WARN",
            f"Questions: {qsf_q} in QSF, {lss_q} in LSS ({diff} fewer) "
            f"— likely Trash block or collapsed Matrix questions"))
    else:
        checks.append(("WARN",
            f"Questions: {qsf_q} in QSF, {lss_q} in LSS ({lss_q - qsf_q} more) "
            f"— extra questions may be from split types"))

    # 2. Group count
    qsf_blocks = s["n_blocks"]
    lss_groups = lss_stats["groups"]
    if lss_groups == qsf_blocks:
        checks.append(("OK", f"Groups match blocks: {qsf_blocks}"))
    elif lss_groups < qsf_blocks:
        diff = qsf_blocks - lss_groups
        checks.append(("WARN",
            f"Groups: {qsf_blocks} blocks in QSF, {lss_groups} groups in LSS "
            f"({diff} fewer — empty or Trash blocks skipped)"))
    else:
        checks.append(("WARN",
            f"Groups: {qsf_blocks} blocks in QSF, {lss_groups} groups in LSS"))

    # 3. Question type coverage
    qsf_types = set()
    for q in questions:
        key = (q["type"], q["selector"])
        qsf_types.add(key)
    unmapped = []
    for key in qsf_types:
        if key not in TYPE_MAP and (key[0], "") not in TYPE_MAP:
            unmapped.append(f"{key[0]}/{key[1]}")
    if unmapped:
        checks.append(("WARN",
            f"Unmapped question types (defaulted to Long Text): {', '.join(unmapped)}"))
    else:
        checks.append(("OK", f"All {len(qsf_types)} question type(s) have mappings"))

    # 4. Answer options
    qsf_total_choices = 0
    for q in questions:
        if q["n_choices"] > 0 and q["type"] not in ("DB", "Timing"):
            qsf_total_choices += q["n_choices"]

    lss_answers = lss_stats["answers"]
    lss_subqs = lss_stats["subquestions"]
    lss_total_options = lss_answers + lss_subqs

    if qsf_total_choices == 0 and lss_total_options == 0:
        checks.append(("OK", "No answer options expected or generated"))
    elif lss_total_options == qsf_total_choices:
        checks.append(("OK",
            f"All {qsf_total_choices} choices accounted for "
            f"({lss_answers} answers + {lss_subqs} subquestions)"))
    else:
        diff = qsf_total_choices - lss_total_options
        if abs(diff) <= max(qsf_total_choices * 0.1, 1):
            checks.append(("OK",
                f"Choices: {qsf_total_choices} in QSF, "
                f"{lss_total_options} in LSS ({lss_answers} answers + {lss_subqs} subquestions) "
                f"— minor difference of {abs(diff)}"))
        else:
            checks.append(("WARN",
                f"Choices: {qsf_total_choices} in QSF, "
                f"{lss_total_options} in LSS ({lss_answers} answers + {lss_subqs} subquestions) "
                f"— difference of {abs(diff)}"))

    # 5. Mandatory / validation
    qsf_mandatory = sum(1 for q in questions if q["force_response"])
    lss_mandatory = lss_stats.get("n_mandatory", 0)
    if qsf_mandatory == lss_mandatory:
        checks.append(("OK", f"Mandatory questions match: {qsf_mandatory}"))
    else:
        checks.append(("WARN",
            f"Mandatory: {qsf_mandatory} in QSF (ForceResponse=ON), "
            f"{lss_mandatory} in LSS"))

    # 6. Display logic → relevance
    qsf_logic = s.get("n_questions_with_display_logic", 0)
    lss_relevance = lss_stats.get("n_with_relevance", 0)
    if qsf_logic == lss_relevance:
        checks.append(("OK", f"Display logic/relevance match: {qsf_logic}"))
    elif qsf_logic > 0 and lss_relevance == 0:
        checks.append(("FAIL",
            f"Display logic: {qsf_logic} questions have logic in QSF, "
            f"but 0 have relevance equations in LSS"))
    elif lss_relevance < qsf_logic:
        checks.append(("WARN",
            f"Display logic: {qsf_logic} in QSF, {lss_relevance} relevance equations in LSS "
            f"— some logic may have been too complex to convert"))
    else:
        checks.append(("OK",
            f"Display logic: {qsf_logic} in QSF, {lss_relevance} in LSS"))

    # 7. Conversion warnings
    if conversion_warnings:
        checks.append(("WARN",
            f"{len(conversion_warnings)} converter warning(s) — review output report"))
    else:
        checks.append(("OK", "No conversion warnings"))

    # 8. Problem types
    if s.get("n_problem_question_types", 0) > 0:
        problem_types = [q["type"] for q in questions if q["is_problem_type"]]
        type_summary = ", ".join(f"{t}({c})" for t, c in Counter(problem_types).most_common())
        checks.append(("WARN",
            f"Problem question types present: {type_summary} "
            f"— these have no clean LimeSurvey equivalent"))

    # 9. JavaScript
    if s.get("n_questions_with_javascript", 0) > 0:
        checks.append(("WARN",
            f"{s['n_questions_with_javascript']} question(s) use custom JavaScript "
            f"— not transferred to LSS, needs manual review"))

    # 10. Embedded data
    ed_fields = s.get("embedded_data_fields", [])
    if ed_fields:
        checks.append(("INFO",
            f"{len(ed_fields)} embedded data field(s) detected: {', '.join(ed_fields[:5])}"
            + (" ..." if len(ed_fields) > 5 else "")
            + " — set these as URL parameters in LimeSurvey"))

    return checks


def write_check_report(w: ReportWriter, checks: list[tuple[str, str]]) -> None:
    w.section("VERIFICATION")

    n_ok = sum(1 for s, _ in checks if s == "OK")
    n_warn = sum(1 for s, _ in checks if s == "WARN")
    n_fail = sum(1 for s, _ in checks if s == "FAIL")
    n_info = sum(1 for s, _ in checks if s == "INFO")

    symbols = {"OK": "[OK]  ", "WARN": "[!!]  ", "FAIL": "[FAIL]", "INFO": "[i]   "}

    for status, message in checks:
        sym = symbols.get(status, "      ")
        w.write(f"    {sym} {message}")

    w.blank()
    verdict_parts = [f"{n_ok} passed"]
    if n_warn:
        verdict_parts.append(f"{n_warn} warning(s)")
    if n_fail:
        verdict_parts.append(f"{n_fail} FAILED")
    if n_info:
        verdict_parts.append(f"{n_info} info")
    w.row("Verdict", " | ".join(verdict_parts))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    input_dir = APP_DIR / "input"
    output_dir = APP_DIR / "output"

    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    qsf_files = sorted(input_dir.glob("*.qsf"))

    w = ReportWriter()

    if not qsf_files:
        w.header("QualtricsToLime Converter")
        w.blank()
        w.write(f"  No .qsf files found in: {input_dir}")
        w.blank()
        w.write("  How to use:")
        w.write("    1. Place your .qsf files in the 'input' folder")
        w.write("    2. Run this program again")
        w.write("    3. Find .lss files in the 'output' folder")
        w.blank()
        input("Press Enter to exit...")
        return 1

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    w.header("QualtricsToLime — Conversion Report")
    w.write(f"  Date: {timestamp}")
    w.write(f"  Found {len(qsf_files)} .qsf file(s)")
    w.write(f"  Input:  {input_dir}")
    w.write(f"  Output: {output_dir}")

    successes = 0
    failures = 0

    for qsf_path in qsf_files:
        out_path = output_dir / qsf_path.with_suffix(".lss").name
        report = None

        # --- Input Report ---
        try:
            report = inspect_one(qsf_path)
            write_input_report(w, qsf_path, report)
        except Exception as exc:
            w.section(f"INPUT: {qsf_path.name}")
            w.write(f"      (inspection failed: {exc})")

        # --- Convert ---
        try:
            lss_xml, warnings = convert_qsf_to_lss(qsf_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(lss_xml, encoding="utf-8")
            successes += 1

            # --- Output Report ---
            lss_stats = analyse_lss(out_path)
            write_output_report(w, out_path, warnings, lss_stats)

            # --- Verification ---
            if report and lss_stats:
                checks = run_checks(report, lss_stats, warnings)
                write_check_report(w, checks)

        except Exception as exc:
            w.blank()
            w.write(f"      CONVERSION FAILED: {exc}")
            failures += 1

        w.blank()
        w.write(f"  {THIN}")

    # --- Final Summary ---
    w.blank()
    w.write(HEADER)
    w.write(f"  SUMMARY: {successes} converted, {failures} failed, {len(qsf_files)} total")
    w.write(f"  Output folder: {output_dir}")
    w.write(HEADER)

    # Save report document
    report_name = f"conversion_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_path = output_dir / report_name
    w.save(report_path)
    w.blank()
    print(f"  Report saved to: {report_path}")
    print()
    input("Press Enter to exit...")

    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
