#!/usr/bin/env python3
"""
qsf_to_lss.py — Convert a Qualtrics .qsf file to a LimeSurvey .lss file.

Handles:
  - Survey metadata
  - Blocks → Question Groups
  - Questions with choices/answers → Questions + Subquestions + Answers
  - Display logic → Relevance equations
  - Survey flow → Group ordering (including block randomizers)
  - Piped text → ExpressionManager references
  - Sliders → Numerical inputs
  - Validation → LimeSurvey mandatory/validation

No external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

# ---------------------------------------------------------------------------
# Question type mapping: (QualticsType, Selector) → LimeSurvey type code
# ---------------------------------------------------------------------------
TYPE_MAP: dict[tuple[str, str], str] = {
    ("MC", "SAVR"): "L",       # single choice radio
    ("MC", "SAHR"): "L",       # single choice horizontal radio
    ("MC", "DL"):   "!",       # dropdown
    ("MC", "MAVR"): "M",       # multiple choice
    ("MC", "MAHR"): "M",       # multiple choice horizontal
    ("MC", "MSB"):  "M",       # multi-select box
    ("TE", "SL"):   "S",       # short text
    ("TE", "ML"):   "T",       # long text
    ("TE", "ESTB"): "T",       # essay text box
    ("TE", "FORM"): "Q",       # multiple short text
    ("Matrix", "Likert"):  "F",  # array
    ("Matrix", "TE"):     ";",   # array text
    ("Matrix", "Bipolar"): "1",  # array dual scale
    ("RO", "DND"):  "R",       # ranking
    ("DB", ""):     "X",       # text display
    ("DB", "TB"):   "X",       # text display
    ("DB", "GRB"):  "X",       # graphic text display
    ("Slider", "HSLIDER"): "N",  # numerical
    ("Slider", "HBAR"):   "N",  # numerical
    ("CS", ""):     "K",       # multiple numerical (constant sum)
    ("SBS", ""):    "F",       # side-by-side → array (best effort)
    ("PGR", ""):    "R",       # pick-group-rank → ranking
    ("Timing", "I"): "X",      # timing → display (no LS equivalent)
}

# LimeSurvey question types that use subquestions (rows)
SUBQUESTION_TYPES = {"F", ";", ":", "1", "H", "K", "R"}

# LimeSurvey question types that use answer options (columns/scales)
ANSWER_TYPES = {"L", "!", "M", "F", "1", "R"}

# DB version for LimeSurvey 5.x compatibility
DB_VERSION = "500"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def cdata(text: str) -> str:
    """Wrap text in CDATA markers. We'll handle this at XML output time."""
    return text


def add_row_field(row: Element, tag: str, value: str) -> None:
    """Add a field to a row element, using CDATA for text content."""
    el = SubElement(row, tag)
    el.text = value


def get_elements(qsf: dict, kind: str) -> list[dict]:
    return [e for e in qsf.get("SurveyElements", []) if e.get("Element") == kind]


def resolve_ls_type(qtype: str, selector: str) -> str:
    """Map Qualtrics question type to LimeSurvey type code."""
    # Try exact match first, then with empty selector
    ls_type = TYPE_MAP.get((qtype, selector))
    if ls_type is None:
        ls_type = TYPE_MAP.get((qtype, ""))
    if ls_type is None:
        ls_type = "T"  # fallback: long free text
    return ls_type


# ---------------------------------------------------------------------------
# Piped text / expression conversion
# ---------------------------------------------------------------------------
PIPED_TEXT_RE = re.compile(r"\$\{e://Field/([^}]+)\}")
PIPED_QID_RE = re.compile(r"\$\{q://([^/]+)/([^}]+)\}")
PIPED_LOOP_RE = re.compile(r"\$\{lm://Field/\d+\}")
PIPED_GENERIC_RE = re.compile(r"\$\{([^}]+)\}")


def convert_piped_text(text: str, tag_map: dict[str, str]) -> str:
    """Convert Qualtrics piped text to LimeSurvey ExpressionManager syntax.

    Qualtrics: ${e://Field/FieldName} or ${q://QID123/QuestionText}
    LimeSurvey: {FieldName} or {Q1.question}
    """
    if not text:
        return text

    # Embedded data fields: ${e://Field/Name} → {Name}
    text = PIPED_TEXT_RE.sub(r"{\1}", text)

    # Question references: ${q://QID123/ChoiceTextEntryValue} → {tag.NAOK}
    def replace_qref(m: re.Match) -> str:
        qid = m.group(1)
        prop = m.group(2)
        tag = tag_map.get(qid, qid)
        if "ChoiceTextEntryValue" in prop or "SelectedChoicesTextEntry" in prop:
            return "{" + tag + ".NAOK}"
        if "QuestionText" in prop:
            return "{" + tag + ".question}"
        return "{" + tag + ".NAOK}"

    text = PIPED_QID_RE.sub(replace_qref, text)

    # Generic fallback: ${anything} → {anything}
    text = PIPED_LOOP_RE.sub("{FIXME_LOOP_REF}", text)

    return text


# ---------------------------------------------------------------------------
# Display logic → Relevance equation
# ---------------------------------------------------------------------------
def convert_display_logic(logic: dict | None, tag_map: dict[str, str]) -> str:
    """Convert Qualtrics DisplayLogic to a LimeSurvey relevance equation.

    Returns "1" (always show) if no logic or if conversion fails.
    For complex cases, returns a best-effort expression with FIXME markers.
    """
    if not logic:
        return "1"

    parts = []

    def extract_conditions(node: Any, depth: int = 0) -> None:
        if not isinstance(node, dict):
            return

        # Check if this is a condition node
        if "Type" in node and node.get("Type") in ("If", "Expression"):
            operator = node.get("Operator", "")
            left_operand = node.get("LeftOperand", "")
            # Try to extract the question reference
            qid_match = re.search(r"q://([^/]+)", left_operand) if isinstance(left_operand, str) else None
            choice_locator = node.get("ChoiceLocator", "")
            right_operand = node.get("RightOperand", "")

            if qid_match:
                qid = qid_match.group(1)
                tag = tag_map.get(qid, qid)

                if choice_locator:
                    # Extract choice number from locator like "q://QID5/SelectableChoice/3"
                    choice_match = re.search(r"/(\d+)$", choice_locator)
                    choice_code = choice_match.group(1) if choice_match else ""

                    if operator == "Selected":
                        parts.append(f'({tag}_{choice_code}.NAOK == "Y")')
                    elif operator == "NotSelected":
                        parts.append(f'({tag}_{choice_code}.NAOK != "Y")')
                    elif operator == "EqualTo":
                        parts.append(f'({tag}_{choice_code}.NAOK == "{right_operand}")')
                    elif operator == "NotEqualTo":
                        parts.append(f'({tag}_{choice_code}.NAOK != "{right_operand}")')
                    else:
                        parts.append(f"/* FIXME: {operator} on {tag}_{choice_code} */1")
                else:
                    if operator == "EqualTo":
                        parts.append(f'({tag}.NAOK == "{right_operand}")')
                    elif operator == "NotEqualTo":
                        parts.append(f'({tag}.NAOK != "{right_operand}")')
                    elif operator == "GreaterThan":
                        parts.append(f"({tag}.NAOK > {right_operand})")
                    elif operator == "LessThan":
                        parts.append(f"({tag}.NAOK < {right_operand})")
                    elif operator == "GreaterThanOrEqual":
                        parts.append(f"({tag}.NAOK >= {right_operand})")
                    elif operator == "LessThanOrEqual":
                        parts.append(f"({tag}.NAOK <= {right_operand})")
                    elif operator == "IsDisplayed":
                        parts.append(f"(!is_empty({tag}.NAOK))")
                    elif operator == "IsNotDisplayed":
                        parts.append(f"(is_empty({tag}.NAOK))")
                    elif operator == "IsEmpty":
                        parts.append(f"(is_empty({tag}.NAOK))")
                    elif operator == "IsNotEmpty":
                        parts.append(f"(!is_empty({tag}.NAOK))")
                    elif operator == "Selected":
                        parts.append(f'({tag}.NAOK == "Y")')
                    elif operator == "NotSelected":
                        parts.append(f'({tag}.NAOK != "Y")')
                    elif operator in ("Contains", "Matches"):
                        parts.append(f'(regexMatch("/{right_operand}/", {tag}.NAOK))')
                    else:
                        parts.append(f"/* FIXME: {operator} on {tag} */ 1")

        # Walk children
        conjunctions = []
        for key, val in node.items():
            if key in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
                extract_conditions(val, depth + 1)
            elif key == "BooleanExpression":
                extract_conditions(val, depth + 1)
            elif key == "Conjunction":
                conjunctions.append(val)

    try:
        extract_conditions(logic)
    except Exception:
        return "/* FIXME: complex display logic needs manual review */ 1"

    if not parts:
        return "1"

    # Join with AND by default (most common in Qualtrics)
    return " && ".join(parts)


# ---------------------------------------------------------------------------
# Survey builder
# ---------------------------------------------------------------------------
class LSSBuilder:
    """Builds an LSS XML document from parsed QSF data."""

    def __init__(self, qsf: dict[str, Any]):
        self.qsf = qsf
        self.sid = 100000  # survey id
        self.gid_counter = 1
        self.qid_counter = 1
        self.language = qsf.get("SurveyEntry", {}).get("SurveyLanguage", "en") or "en"

        # Build QID → DataExportTag map for cross-references
        self.tag_map: dict[str, str] = {}
        for sq in get_elements(qsf, "SQ"):
            p = sq.get("Payload", {})
            qid = p.get("QuestionID", "")
            tag = p.get("DataExportTag", "") or qid
            self.tag_map[qid] = tag

        # Parse blocks
        self.blocks = self._parse_blocks()
        # Parse flow to get block ordering
        self.block_order = self._parse_flow_order()

        # Storage for XML sections
        self.groups_rows: list[dict] = []
        self.questions_rows: list[dict] = []
        self.subquestions_rows: list[dict] = []
        self.answers_rows: list[dict] = []
        self.question_attributes_rows: list[dict] = []

        # Block ID → GID mapping
        self.block_gid_map: dict[str, int] = {}

        # Track warnings for post-conversion review
        self.warnings: list[str] = []

    def _parse_blocks(self) -> dict[str, dict]:
        """Parse blocks from QSF, returning {block_id: block_data}."""
        blocks = {}
        for bl in get_elements(self.qsf, "BL"):
            payload = bl.get("Payload", [])
            if isinstance(payload, dict):
                items = list(payload.values())
            elif isinstance(payload, list):
                items = payload
            else:
                items = []
            for b in items:
                if not isinstance(b, dict):
                    continue
                bid = b.get("ID", "")
                if bid:
                    blocks[bid] = b
        return blocks

    def _parse_flow_order(self) -> list[str]:
        """Extract block ordering from survey flow. Returns list of block IDs."""
        order = []
        fl_elems = get_elements(self.qsf, "FL")
        if not fl_elems:
            return list(self.blocks.keys())

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("Type") in ("Block", "Standard"):
                    bid = node.get("ID", "")
                    if bid and bid not in order:
                        order.append(bid)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(fl_elems[0].get("Payload", {}))

        # Add any blocks not in flow
        for bid in self.blocks:
            if bid not in order:
                order.append(bid)

        return order

    def _get_questions_for_block(self, block_id: str) -> list[dict]:
        """Get all question payloads belonging to a block."""
        block = self.blocks.get(block_id, {})
        block_elements = block.get("BlockElements", [])
        qids_in_block = set()
        for be in block_elements:
            if be.get("Type") == "Question":
                qids_in_block.add(be.get("QuestionID", ""))

        questions = []
        for sq in get_elements(self.qsf, "SQ"):
            p = sq.get("Payload", {})
            if p.get("QuestionID", "") in qids_in_block:
                questions.append(p)
        return questions

    def build(self) -> str:
        """Build the complete LSS XML and return as string."""
        # Skip trash/unused blocks
        for block_id in self.block_order:
            block = self.blocks.get(block_id, {})
            desc = block.get("Description", "")
            if "Trash" in desc or "Unused" in desc:
                continue

            questions = self._get_questions_for_block(block_id)
            if not questions:
                continue

            gid = self.gid_counter
            self.gid_counter += 1
            self.block_gid_map[block_id] = gid

            # Create group
            self.groups_rows.append({
                "gid": str(gid),
                "sid": str(self.sid),
                "group_name": desc or f"Group {gid}",
                "group_order": str(gid - 1),
                "description": "",
                "language": self.language,
                "randomization_group": "",
                "grelevance": "1",
            })

            # Create questions within the group
            for q in questions:
                self._convert_question(q, gid)

        return self._render_xml()

    def _convert_question(self, q: dict, gid: int) -> None:
        """Convert a single Qualtrics question to LimeSurvey question rows."""
        qtype = q.get("QuestionType", "")
        selector = q.get("Selector", "")
        subselector = q.get("SubSelector", "")
        qid = self.qid_counter
        self.qid_counter += 1
        qualtrics_qid = q.get("QuestionID", "")
        tag = q.get("DataExportTag", "") or f"Q{qid}"
        question_text = q.get("QuestionText", "") or ""
        ls_type = resolve_ls_type(qtype, selector)

        # Convert piped text in question body
        question_text = convert_piped_text(question_text, self.tag_map)

        # Convert display logic to relevance
        relevance = convert_display_logic(q.get("DisplayLogic"), self.tag_map)

        # Mandatory
        mandatory = "Y" if q.get("Validation", {}).get("Settings", {}).get("ForceResponse") == "ON" else "N"

        # Track unmapped types
        if (qtype, selector) not in TYPE_MAP and (qtype, "") not in TYPE_MAP:
            self.warnings.append(
                f"Question {tag} ({qualtrics_qid}): type {qtype}/{selector} unmapped, defaulting to T (long text)"
            )

        # Main question row
        self.questions_rows.append({
            "qid": str(qid),
            "parent_qid": "0",
            "sid": str(self.sid),
            "gid": str(gid),
            "type": ls_type,
            "title": tag,
            "question": question_text,
            "help": "",
            "preg": "",
            "other": "N",
            "mandatory": mandatory,
            "encrypted": "N",
            "question_order": str(qid),
            "scale_id": "0",
            "same_default": "0",
            "relevance": relevance,
            "question_theme_name": "",
            "modulename": "",
            "same_script": "0",
            "language": self.language,
        })

        # Handle choices → either answers (for L, !, M) or subquestions (for F, R, etc.)
        choices = q.get("Choices", {})
        choice_order = q.get("ChoiceOrder", [])
        if not choice_order and isinstance(choices, dict):
            choice_order = list(choices.keys())

        answers = q.get("Answers", {})
        answer_order = q.get("AnswerOrder", [])
        if not answer_order and isinstance(answers, dict):
            answer_order = list(answers.keys())

        if ls_type in SUBQUESTION_TYPES and choices:
            # Choices become subquestions (rows of the array)
            for sort_order, choice_key in enumerate(choice_order):
                choice_key_str = str(choice_key)
                choice = choices.get(choice_key_str, {})
                if not isinstance(choice, dict):
                    continue
                display = choice.get("Display", f"Choice {choice_key_str}")
                display = convert_piped_text(display, self.tag_map)

                sq_qid = self.qid_counter
                self.qid_counter += 1
                # Subquestion title: SQ001, SQ002, etc.
                sq_code = f"SQ{sort_order + 1:03d}"

                self.subquestions_rows.append({
                    "qid": str(sq_qid),
                    "parent_qid": str(qid),
                    "sid": str(self.sid),
                    "gid": str(gid),
                    "type": ls_type,
                    "title": sq_code,
                    "question": display,
                    "help": "",
                    "preg": "",
                    "other": "N",
                    "mandatory": "N",
                    "encrypted": "N",
                    "question_order": str(sort_order + 1),
                    "scale_id": "0",
                    "same_default": "0",
                    "relevance": "1",
                    "question_theme_name": "",
                    "modulename": "",
                    "same_script": "0",
                    "language": self.language,
                })

            # For array types, answers become the scale (column headers)
            if answers and ls_type in ("F", "1"):
                for sort_order, ans_key in enumerate(answer_order):
                    ans_key_str = str(ans_key)
                    ans = answers.get(ans_key_str, {})
                    if not isinstance(ans, dict):
                        continue
                    display = ans.get("Display", f"Answer {ans_key_str}")
                    display = convert_piped_text(display, self.tag_map)

                    self.answers_rows.append({
                        "qid": str(qid),
                        "code": f"A{sort_order + 1}",
                        "answer": display,
                        "sortorder": str(sort_order),
                        "assessment_value": "0",
                        "language": self.language,
                        "scale_id": "0",
                    })

        elif ls_type in ANSWER_TYPES and choices:
            # Choices become answer options
            for sort_order, choice_key in enumerate(choice_order):
                choice_key_str = str(choice_key)
                choice = choices.get(choice_key_str, {})
                if not isinstance(choice, dict):
                    continue
                display = choice.get("Display", f"Choice {choice_key_str}")
                display = convert_piped_text(display, self.tag_map)

                self.answers_rows.append({
                    "qid": str(qid),
                    "code": f"A{sort_order + 1}",
                    "answer": display,
                    "sortorder": str(sort_order),
                    "assessment_value": "0",
                    "language": self.language,
                    "scale_id": "0",
                })

        # Handle "Other" option
        if q.get("Configuration", {}).get("QuestionDescriptionOption") == "UseText":
            pass  # description-only, no special handling
        # Check for "Other" in MC questions
        if qtype == "MC" and ls_type in ("L", "M"):
            # Some MC questions have an "Other" text entry option
            for choice_key, choice in choices.items():
                if isinstance(choice, dict) and choice.get("TextEntry") == "true":
                    # Update main question to allow "other"
                    self.questions_rows[-1]["other"] = "Y" if ls_type == "L" else "N"
                    break

        # Slider-specific attributes
        if qtype == "Slider":
            config = q.get("Configuration", {})
            slider_min = config.get("CSSliderMin", "0")
            slider_max = config.get("CSSliderMax", "100")
            self.question_attributes_rows.append({
                "qid": str(qid),
                "attribute": "slider_min",
                "value": str(slider_min),
                "language": "",
            })
            self.question_attributes_rows.append({
                "qid": str(qid),
                "attribute": "slider_max",
                "value": str(slider_max),
                "language": "",
            })

    def _render_xml(self) -> str:
        """Render the complete LSS XML document."""
        doc = Element("document")

        # Doc type
        doc_type = SubElement(doc, "LimeSurveyDocType")
        doc_type.text = "Survey"
        db_ver = SubElement(doc, "DBVersion")
        db_ver.text = DB_VERSION

        # Languages
        langs = SubElement(doc, "languages")
        lang_el = SubElement(langs, "language")
        lang_el.text = self.language

        # --- surveys table ---
        entry = self.qsf.get("SurveyEntry", {})
        self._add_table(doc, "surveys", [{
            "sid": str(self.sid),
            "admin": "admin",
            "adminemail": "admin@example.com",
            "anonymized": "N",
            "format": "G",  # Group by group
            "assessments": "N",
            "showxquestions": "Y",
            "showgroupinfo": "B",
            "shownoanswer": "Y",
            "showqnumcode": "X",
            "showwelcome": "Y",
            "show_title": "Y",
            "show_group_name": "Y",
            "show_group_description": "Y",
            "showprogress": "Y",
            "questionindex": "0",
            "navigationdelay": "0",
            "nokeyboard": "N",
            "alloweditaftercompletion": "N",
            "printanswers": "N",
            "publicstatistics": "N",
            "autoredirect": "N",
            "allowregister": "N",
            "allowsave": "Y",
            "active": "N",
            "language": self.language,
            "additional_languages": "",
            "datestamp": "Y",
            "usecookie": "N",
            "allowprev": "Y",
            "tokenanswerspersistence": "N",
            "surveyls_survey_id": str(self.sid),
            "surveyls_language": self.language,
            "surveyls_title": entry.get("SurveyName", "Converted Survey"),
            "surveyls_description": entry.get("SurveyDescription", ""),
            "surveyls_welcometext": "",
            "surveyls_endtext": "",
            "surveyls_dateformat": "1",
            "surveyls_numberformat": "0",
        }])

        # --- surveys_languagesettings table ---
        self._add_table(doc, "surveys_languagesettings", [{
            "surveyls_survey_id": str(self.sid),
            "surveyls_language": self.language,
            "surveyls_title": entry.get("SurveyName", "Converted Survey"),
            "surveyls_description": entry.get("SurveyDescription", ""),
            "surveyls_welcometext": "",
            "surveyls_endtext": "",
            "surveyls_url": "",
            "surveyls_urldescription": "",
            "surveyls_dateformat": "1",
            "surveyls_numberformat": "0",
        }])

        # --- groups table ---
        self._add_table(doc, "groups", self.groups_rows)

        # --- questions table ---
        self._add_table(doc, "questions", self.questions_rows)

        # --- subquestions table ---
        if self.subquestions_rows:
            self._add_table(doc, "subquestions", self.subquestions_rows)

        # --- answers table ---
        if self.answers_rows:
            self._add_table(doc, "answers", self.answers_rows)

        # --- question_attributes table ---
        if self.question_attributes_rows:
            self._add_table(doc, "question_attributes", self.question_attributes_rows)

        # --- conditions (empty) ---
        self._add_table(doc, "conditions", [])

        # Pretty-print
        raw_xml = tostring(doc, encoding="unicode")
        # Wrap in XML declaration
        raw_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw_xml
        try:
            pretty = parseString(raw_xml).toprettyxml(indent="  ", encoding=None)
            # Remove the extra xml declaration from toprettyxml
            lines = pretty.split("\n")
            if lines[0].startswith("<?xml"):
                lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
            return "\n".join(lines)
        except Exception:
            return raw_xml

    def _add_table(self, parent: Element, table_name: str, rows: list[dict]) -> None:
        """Add a table section to the XML document."""
        table = SubElement(parent, table_name)
        rows_el = SubElement(table, "rows")
        for row_data in rows:
            row = SubElement(rows_el, "row")
            for key, value in row_data.items():
                field = SubElement(row, key)
                # Use CDATA for text fields that might contain HTML
                if key in ("question", "help", "answer", "group_name", "description",
                           "surveyls_title", "surveyls_description", "surveyls_welcometext",
                           "surveyls_endtext", "surveyls_urldescription"):
                    field.text = value  # minidom will escape as needed
                else:
                    field.text = str(value) if value is not None else ""

    def get_warnings(self) -> list[str]:
        return self.warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def convert_qsf_to_lss(qsf_path: Path) -> tuple[str, list[str]]:
    """Convert a QSF file to LSS XML string.

    Returns (lss_xml_string, list_of_warnings).
    """
    with qsf_path.open("r", encoding="utf-8") as f:
        qsf = json.load(f)

    builder = LSSBuilder(qsf)
    lss_xml = builder.build()
    return lss_xml, builder.get_warnings()


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python qsf_to_lss.py input.qsf [output.lss]", file=sys.stderr)
        return 1

    qsf_path = Path(sys.argv[1])
    if not qsf_path.exists():
        print(f"File not found: {qsf_path}", file=sys.stderr)
        return 1

    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else qsf_path.with_suffix(".lss")

    lss_xml, warnings = convert_qsf_to_lss(qsf_path)

    out_path.write_text(lss_xml, encoding="utf-8")
    print(f"Converted: {qsf_path.name} -> {out_path.name}")

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
