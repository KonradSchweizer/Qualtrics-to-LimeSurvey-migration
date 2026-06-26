#!/usr/bin/env python3
"""
qsf_inspector.py — Audit Qualtrics .qsf files before migration to LimeSurvey.

Walks a folder of .qsf files and produces:
  - per-survey JSON dump of features detected
  - one CSV row per survey (high-level summary)
  - one CSV row per question (across all surveys, for type-level analysis)
  - aggregate report (console + JSON) showing what features your surveys
    actually use, so you know what the converter must support.

Usage:
    python qsf_inspector.py /path/to/qsf/folder
    python qsf_inspector.py /path/to/qsf/folder --out /path/to/results
    python qsf_inspector.py single_file.qsf

No external dependencies — stdlib only.

Author: built for Konrad's Qualtrics → LimeSurvey migration pipeline.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Mapping reference: what we know maps cleanly to LimeSurvey.
# Keyed by (QuestionType, Selector). Used only to flag "safe" vs "needs review".
# ---------------------------------------------------------------------------
SAFE_MAPPINGS: dict[tuple[str, str], str] = {
    ("MC", "SAVR"): "list_radio (L)",         # MC single, vertical
    ("MC", "SAHR"): "list_radio (L)",         # MC single, horizontal
    ("MC", "DL"):   "list_dropdown (!)",      # dropdown
    ("MC", "MAVR"): "multiple_choice (M)",    # MC multi, vertical
    ("MC", "MAHR"): "multiple_choice (M)",    # MC multi, horizontal
    ("MC", "MSB"):  "multiple_choice (M)",    # multi-select box
    ("TE", "SL"):   "short_free_text (S)",
    ("TE", "ML"):   "long_free_text (T)",
    ("TE", "ESTB"): "long_free_text (T)",     # essay text box
    ("TE", "FORM"): "multiple_short_text (Q)",
    ("Matrix", "Likert"):    "array (F)",
    ("Matrix", "TE"):        "array_text (;)",
    ("Matrix", "Bipolar"):   "array_dual_scale (1)",
    ("RO", "DND"):  "ranking (R)",            # rank order drag/drop
    ("DB", ""):     "text_display (X)",       # descriptive block
    ("DB", "TB"):   "text_display (X)",
    ("Slider", "HSLIDER"):   "numerical (N) — review range",
    ("Slider", "HBAR"):      "numerical (N) — review range",
    ("SBS", ""):    "array (F) — needs splitting",  # side-by-side, awkward
    ("CS", ""):     "multiple_numerical (K)", # constant sum
    ("PGR", ""):    "ranking (R) — review",   # pick group rank
}

# Question types we know don't have a clean LimeSurvey equivalent.
PROBLEM_TYPES = {"HeatMap", "HotSpot", "GAP", "TX", "Captcha", "Timing", "Meta", "FileUpload"}

# Display-logic operators we'll need to translate into ExpressionScript.
LOGIC_OPERATORS_OF_INTEREST = {
    "Selected", "NotSelected", "EqualTo", "NotEqualTo",
    "GreaterThan", "LessThan", "GreaterThanOrEqual", "LessThanOrEqual",
    "Is", "IsNot", "IsDisplayed", "IsNotDisplayed",
    "Contains", "DoesNotContain", "IsEmpty", "IsNotEmpty",
    "Matches", "DoesNotMatch",
}

PIPED_TEXT_RE = re.compile(r"\$\{[^}]+\}")
QREF_RE = re.compile(r"q://[A-Za-z0-9_]+/[A-Za-z0-9_./]+")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_qsf(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_elements(qsf: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Return all SurveyElements of a given kind ('SQ', 'BL', 'FL', 'SO', ...)."""
    return [e for e in qsf.get("SurveyElements", []) if e.get("Element") == kind]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def extract_meta(qsf: dict[str, Any], path: Path) -> dict[str, Any]:
    entry = qsf.get("SurveyEntry", {})
    return {
        "file": path.name,
        "survey_id": entry.get("SurveyID", ""),
        "survey_name": entry.get("SurveyName", path.stem),
        "language": entry.get("SurveyLanguage", ""),
        "creation_date": entry.get("CreationDate", ""),
        "last_modified": entry.get("LastModified", ""),
    }


def analyse_display_logic(payload: dict[str, Any]) -> tuple[int, Counter]:
    """Return (n_conditions, Counter(operators_used)) for one question's display logic."""
    logic = payload.get("DisplayLogic")
    if not logic:
        return 0, Counter()
    ops: Counter = Counter()
    n = 0

    def walk(node: Any) -> None:
        nonlocal n
        if isinstance(node, dict):
            if node.get("Type") in {"If", "Expression"} and "Operator" in node:
                n += 1
                ops[node["Operator"]] += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(logic)
    return n, ops


def text_features(text: str) -> dict[str, int]:
    """Count piped-text and q-ref patterns in a string."""
    if not text:
        return {"piped_text": 0, "q_refs": 0}
    return {
        "piped_text": len(PIPED_TEXT_RE.findall(text)),
        "q_refs": len(QREF_RE.findall(text)),
    }


def analyse_question(sq: dict[str, Any]) -> dict[str, Any]:
    p = sq.get("Payload", {})
    qtype = p.get("QuestionType", "")
    selector = p.get("Selector", "")
    subselector = p.get("SubSelector", "")
    qid = p.get("QuestionID", "")
    dex = p.get("DataExportTag", "")
    qtext = p.get("QuestionText", "") or ""

    n_logic_conds, logic_ops = analyse_display_logic(p)
    tf = text_features(qtext)

    has_js = bool(p.get("QuestionJS"))
    has_validation = bool(p.get("Validation", {}).get("Settings", {}).get("ForceResponse")) or \
                     bool(p.get("Validation", {}).get("Settings", {}).get("Type"))
    val_type = p.get("Validation", {}).get("Settings", {}).get("Type", "")
    force_response = p.get("Validation", {}).get("Settings", {}).get("ForceResponse") == "ON"

    rand = p.get("Randomization", {})
    has_choice_randomization = bool(rand and rand.get("Type", "None") != "None")

    n_choices = len(p.get("Choices", {})) if isinstance(p.get("Choices"), dict) else 0
    n_answers = len(p.get("Answers", {})) if isinstance(p.get("Answers"), dict) else 0

    mapping = SAFE_MAPPINGS.get((qtype, selector))
    if mapping is None and (qtype, "") in SAFE_MAPPINGS:
        mapping = SAFE_MAPPINGS[(qtype, "")]
    is_problem = qtype in PROBLEM_TYPES

    return {
        "qid": qid,
        "data_export_tag": dex,
        "type": qtype,
        "selector": selector,
        "subselector": subselector,
        "type_key": f"{qtype}/{selector}" + (f"/{subselector}" if subselector else ""),
        "n_choices": n_choices,
        "n_answers": n_answers,
        "n_display_logic_conditions": n_logic_conds,
        "display_logic_operators": dict(logic_ops),
        "has_question_js": has_js,
        "has_validation": has_validation,
        "validation_type": val_type,
        "force_response": force_response,
        "has_choice_randomization": has_choice_randomization,
        "piped_text_in_qtext": tf["piped_text"],
        "q_refs_in_qtext": tf["q_refs"],
        "limesurvey_mapping": mapping or "UNMAPPED — manual review",
        "is_problem_type": is_problem,
    }


def analyse_blocks(qsf: dict[str, Any]) -> dict[str, Any]:
    """Summarise block-level features."""
    bl_elems = get_elements(qsf, "BL")
    n_blocks = 0
    n_randomized_blocks = 0
    randomization_types: Counter = Counter()
    for bl in bl_elems:
        payload = bl.get("Payload", [])
        # Payload is sometimes a list of blocks, sometimes a dict keyed by block id
        if isinstance(payload, dict):
            blocks = list(payload.values())
        elif isinstance(payload, list):
            blocks = payload
        else:
            blocks = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            n_blocks += 1
            opts = b.get("Options", {}) or {}
            rand = opts.get("RandomizeQuestions", "false")
            if rand and rand not in ("false", False, "", None):
                n_randomized_blocks += 1
                randomization_types[str(rand)] += 1
    return {
        "n_blocks": n_blocks,
        "n_randomized_blocks": n_randomized_blocks,
        "block_randomization_types": dict(randomization_types),
    }


def analyse_flow(qsf: dict[str, Any]) -> dict[str, Any]:
    """Summarise flow-level features: branches, embedded data, randomizers, quotas."""
    fl_elems = get_elements(qsf, "FL")
    counts: Counter = Counter()
    embedded_data_fields: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("Type")
            if t:
                counts[t] += 1
            if t == "EmbeddedData":
                for ed in node.get("EmbeddedData", []) or []:
                    if isinstance(ed, dict) and "Field" in ed:
                        embedded_data_fields.append(ed["Field"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for fl in fl_elems:
        walk(fl.get("Payload", {}))

    return {
        "flow_element_counts": dict(counts),
        "n_branches": counts.get("Branch", 0),
        "n_randomizers": counts.get("BlockRandomizer", 0) + counts.get("Randomizer", 0),
        "n_end_survey_nodes": counts.get("EndSurvey", 0),
        "n_embedded_data_blocks": counts.get("EmbeddedData", 0),
        "embedded_data_fields": embedded_data_fields,
    }


def analyse_survey_options(qsf: dict[str, Any]) -> dict[str, Any]:
    so = get_elements(qsf, "SO")
    if not so:
        return {}
    payload = so[0].get("Payload", {}) or {}
    return {
        "has_custom_css": bool(payload.get("CustomStyles") or payload.get("Header") or payload.get("Footer")),
        "back_button": payload.get("BackButton", ""),
        "save_and_continue": payload.get("SaveAndContinue", ""),
        "show_question_numbers": payload.get("QuestionsPerPage", ""),
    }


# ---------------------------------------------------------------------------
# Per-file inspection
# ---------------------------------------------------------------------------
def inspect_one(path: Path) -> dict[str, Any]:
    qsf = load_qsf(path)
    meta = extract_meta(qsf, path)

    questions = [analyse_question(sq) for sq in get_elements(qsf, "SQ")]
    blocks = analyse_blocks(qsf)
    flow = analyse_flow(qsf)
    so = analyse_survey_options(qsf)

    # Aggregate per-question features into per-survey counts.
    type_counter: Counter = Counter()
    logic_op_counter: Counter = Counter()
    n_with_logic = 0
    n_with_js = 0
    n_with_validation = 0
    n_with_choice_rand = 0
    n_piped_text = 0
    n_problem = 0
    n_unmapped = 0

    for q in questions:
        type_counter[q["type_key"]] += 1
        if q["n_display_logic_conditions"] > 0:
            n_with_logic += 1
            for op, c in q["display_logic_operators"].items():
                logic_op_counter[op] += c
        if q["has_question_js"]:
            n_with_js += 1
        if q["has_validation"]:
            n_with_validation += 1
        if q["has_choice_randomization"]:
            n_with_choice_rand += 1
        if q["piped_text_in_qtext"]:
            n_piped_text += q["piped_text_in_qtext"]
        if q["is_problem_type"]:
            n_problem += 1
        if q["limesurvey_mapping"].startswith("UNMAPPED"):
            n_unmapped += 1

    # Naive risk score: rough heuristic to sort surveys by migration difficulty.
    risk = (
        n_problem * 5
        + n_unmapped * 3
        + n_with_js * 4
        + n_piped_text * 1
        + flow["n_branches"] * 2
        + flow["n_randomizers"] * 2
        + blocks["n_randomized_blocks"] * 1
        + n_with_logic * 1
    )

    summary = {
        **meta,
        "n_questions": len(questions),
        **blocks,
        **flow,
        **so,
        "question_types": dict(type_counter),
        "display_logic_operators_used": dict(logic_op_counter),
        "n_questions_with_display_logic": n_with_logic,
        "n_questions_with_javascript": n_with_js,
        "n_questions_with_validation": n_with_validation,
        "n_questions_with_choice_randomization": n_with_choice_rand,
        "n_piped_text_occurrences": n_piped_text,
        "n_problem_question_types": n_problem,
        "n_unmapped_question_types": n_unmapped,
        "migration_risk_score": risk,
    }

    return {"summary": summary, "questions": questions}


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------
SUMMARY_COLUMNS = [
    "file", "survey_name", "survey_id", "language",
    "n_questions", "n_blocks", "n_randomized_blocks",
    "n_branches", "n_randomizers", "n_embedded_data_blocks",
    "n_questions_with_display_logic",
    "n_questions_with_javascript",
    "n_questions_with_validation",
    "n_questions_with_choice_randomization",
    "n_piped_text_occurrences",
    "n_problem_question_types",
    "n_unmapped_question_types",
    "migration_risk_score",
]


def write_outputs(reports: list[dict[str, Any]], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. One summary CSV row per survey.
    with (outdir / "summary_per_survey.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(reports, key=lambda x: -x["summary"]["migration_risk_score"]):
            w.writerow(r["summary"])

    # 2. One CSV row per question (across all surveys).
    qcols = [
        "file", "survey_name", "qid", "data_export_tag",
        "type", "selector", "subselector", "type_key",
        "n_choices", "n_answers",
        "n_display_logic_conditions", "has_question_js",
        "has_validation", "validation_type", "force_response",
        "has_choice_randomization", "piped_text_in_qtext", "q_refs_in_qtext",
        "limesurvey_mapping", "is_problem_type",
    ]
    with (outdir / "questions_all.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=qcols, extrasaction="ignore")
        w.writeheader()
        for r in reports:
            for q in r["questions"]:
                row = {**q, "file": r["summary"]["file"], "survey_name": r["summary"]["survey_name"]}
                w.writerow(row)

    # 3. Per-survey JSON dumps (full detail for any deep dive).
    json_dir = outdir / "per_survey_json"
    json_dir.mkdir(exist_ok=True)
    for r in reports:
        stem = Path(r["summary"]["file"]).stem
        with (json_dir / f"{stem}.json").open("w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, ensure_ascii=False)

    # 4. Aggregate report across all surveys.
    agg = aggregate(reports)
    with (outdir / "aggregate_report.json").open("w", encoding="utf-8") as f:
        json.dump(agg, f, indent=2, ensure_ascii=False)


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    type_total: Counter = Counter()
    logic_op_total: Counter = Counter()
    mapping_status: Counter = Counter()
    problem_types: Counter = Counter()
    flow_types: Counter = Counter()
    n_surveys = len(reports)
    totals = defaultdict(int)

    for r in reports:
        s = r["summary"]
        for k, v in s.get("question_types", {}).items():
            type_total[k] += v
        for k, v in s.get("display_logic_operators_used", {}).items():
            logic_op_total[k] += v
        for k, v in s.get("flow_element_counts", {}).items():
            flow_types[k] += v
        for key in (
            "n_questions", "n_blocks", "n_randomized_blocks",
            "n_branches", "n_randomizers", "n_embedded_data_blocks",
            "n_questions_with_display_logic", "n_questions_with_javascript",
            "n_questions_with_validation", "n_questions_with_choice_randomization",
            "n_piped_text_occurrences", "n_problem_question_types",
            "n_unmapped_question_types",
        ):
            totals[key] += s.get(key, 0)
        for q in r["questions"]:
            mapping_status[q["limesurvey_mapping"]] += 1
            if q["is_problem_type"]:
                problem_types[q["type"]] += 1

    return {
        "n_surveys": n_surveys,
        "totals": dict(totals),
        "question_types_across_all_surveys": dict(type_total.most_common()),
        "display_logic_operators_across_all_surveys": dict(logic_op_total.most_common()),
        "flow_element_types_across_all_surveys": dict(flow_types.most_common()),
        "limesurvey_mapping_coverage": dict(mapping_status.most_common()),
        "problem_question_type_counts": dict(problem_types.most_common()),
    }


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------
def print_console_summary(reports: list[dict[str, Any]], agg: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print(f"QSF INSPECTOR — {agg['n_surveys']} survey(s) processed")
    print("=" * 72)

    t = agg["totals"]
    print(f"\nTotals across all surveys:")
    print(f"  Questions:                  {t['n_questions']}")
    print(f"  Blocks:                     {t['n_blocks']}")
    print(f"  Randomized blocks:          {t['n_randomized_blocks']}")
    print(f"  Branches (flow):            {t['n_branches']}")
    print(f"  Randomizers (flow):         {t['n_randomizers']}")
    print(f"  Embedded data blocks:       {t['n_embedded_data_blocks']}")
    print(f"  Questions w/ display logic: {t['n_questions_with_display_logic']}")
    print(f"  Questions w/ JS:            {t['n_questions_with_javascript']}")
    print(f"  Questions w/ validation:    {t['n_questions_with_validation']}")
    print(f"  Questions w/ choice rand.:  {t['n_questions_with_choice_randomization']}")
    print(f"  Piped-text occurrences:     {t['n_piped_text_occurrences']}")
    print(f"  Problem question types:     {t['n_problem_question_types']}")
    print(f"  Unmapped question types:    {t['n_unmapped_question_types']}")

    print(f"\nTop 10 question types used:")
    for k, v in list(agg["question_types_across_all_surveys"].items())[:10]:
        print(f"  {k:40s} {v}")

    if agg["display_logic_operators_across_all_surveys"]:
        print(f"\nDisplay-logic operators in use (these must be translated):")
        for k, v in agg["display_logic_operators_across_all_surveys"].items():
            mark = "  " if k in LOGIC_OPERATORS_OF_INTEREST else "? "
            print(f"  {mark}{k:30s} {v}")

    if agg["problem_question_type_counts"]:
        print(f"\nProblem question types (no clean LimeSurvey equivalent):")
        for k, v in agg["problem_question_type_counts"].items():
            print(f"  {k:30s} {v}")

    print(f"\nMigration risk (highest first):")
    for r in sorted(reports, key=lambda x: -x["summary"]["migration_risk_score"])[:10]:
        s = r["summary"]
        print(f"  {s['migration_risk_score']:5d}  {s['file']}  ({s['n_questions']} Q)")

    print("\n" + "=" * 72)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def find_qsf_files(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() == ".qsf":
        return [target]
    if target.is_dir():
        return sorted(target.rglob("*.qsf"))
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Qualtrics .qsf files for LimeSurvey migration planning.")
    parser.add_argument("target", type=Path, help="Path to a .qsf file or a folder containing .qsf files")
    parser.add_argument("--out", type=Path, default=None, help="Output directory (default: ./qsf_inspector_results_<timestamp>)")
    args = parser.parse_args()

    files = find_qsf_files(args.target)
    if not files:
        print(f"No .qsf files found at {args.target}", file=sys.stderr)
        return 1

    outdir = args.out or Path(f"qsf_inspector_results_{datetime.now():%Y%m%d_%H%M%S}")

    reports: list[dict[str, Any]] = []
    for f in files:
        try:
            print(f"  Inspecting {f.name} …")
            reports.append(inspect_one(f))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! Failed on {f.name}: {exc}", file=sys.stderr)

    if not reports:
        print("No surveys successfully parsed.", file=sys.stderr)
        return 2

    write_outputs(reports, outdir)
    agg = aggregate(reports)
    print_console_summary(reports, agg)
    print(f"\nResults written to: {outdir.resolve()}")
    print("  - summary_per_survey.csv   (one row per survey, sorted by risk)")
    print("  - questions_all.csv        (one row per question across all surveys)")
    print("  - aggregate_report.json    (counts & mapping coverage)")
    print("  - per_survey_json/         (full detail per survey)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
