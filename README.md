# QualtricsToLime

**Converts Qualtrics Survey Files (.qsf) to LimeSurvey Structure files (.lss) with full reporting and verification.**

---

## Quick Start

1. Place your `.qsf` files in the `input/` folder
2. Double-click `QualtricsToLime.exe`
3. Find your `.lss` files and conversion report in the `output/` folder

No Python installation or other software is required.

---

## Folder Structure

```
QualtricsToLime/
|
|-- QualtricsToLime.exe           The converter application
|-- README.md                     This file
|
|-- input/                        Place .qsf files here before running
|
|-- output/                       Results appear here after running
|   |-- *.lss                        Converted LimeSurvey files
|   |-- conversion_report_*.txt      Detailed report document
|
|-- source/                       Python source code
    |-- app.py                       Main application entry point
    |-- convert.py                   CLI entry point
    |-- qsf_to_lss.py               Core converter (QSF JSON -> LSS XML)
    |-- qsf_inspector.py            QSF audit and analysis tool
```

---

## What the Converter Does

The application performs three steps for each `.qsf` file:

### Step 1 — Input Analysis

Inspects the Qualtrics file and reports:

- Survey name, language, creation date
- Number of questions and blocks
- Question type breakdown (MC, Matrix, Slider, etc.)
- Features detected: display logic, validation, piped text, JavaScript, choice randomization, branching, embedded data
- Migration risk score (higher = more complex to migrate)
- Warnings for problem question types

### Step 2 — Conversion

Transforms the QSF structure into LimeSurvey format:

- Blocks become Question Groups
- Questions are mapped to LimeSurvey question types
- Choices become Answer Options or Subquestions
- Display Logic becomes Relevance Equations
- Piped Text becomes ExpressionManager references
- Validation and mandatory settings are preserved
- Slider ranges are converted to numerical input attributes

### Step 3 — Verification

Compares input against output and runs 10 checks:

| Symbol | Meaning |
|--------|---------|
| `[OK]` | Check passed |
| `[!!]` | Warning — minor discrepancy, may be expected |
| `[FAIL]` | Something is likely wrong |
| `[i]` | Informational note |

**Checks performed:**

| # | Check | What it compares |
|---|-------|-----------------|
| 1 | Question count | QSF questions vs LSS questions |
| 2 | Group count | QSF blocks vs LSS question groups |
| 3 | Type coverage | All question types have a mapping |
| 4 | Answer options | Choices accounted for as answers or subquestions |
| 5 | Mandatory questions | ForceResponse matches mandatory flag |
| 6 | Display logic | Logic conditions vs relevance equations |
| 7 | Conversion warnings | Any warnings from the converter |
| 8 | Problem types | Types with no LimeSurvey equivalent |
| 9 | JavaScript | Custom JS flagged for manual review |
| 10 | Embedded data | Fields that need URL parameter setup |

---

## Conversion Report

Each run saves a timestamped report in the output folder:

```
output/conversion_report_20260626_143000.txt
```

The report contains all three sections (input, output, verification) for every file processed, plus an overall summary. Previous reports are never overwritten.

---

## Question Type Mapping

| Qualtrics Type / Selector | LimeSurvey | Description |
|--------------------------|------------|-------------|
| MC / SAVR | L | List (Radio) |
| MC / SAHR | L | List (Radio) horizontal |
| MC / DL | ! | List (Dropdown) |
| MC / MAVR | M | Multiple Choice |
| MC / MAHR | M | Multiple Choice horizontal |
| MC / MSB | M | Multi-Select Box |
| TE / SL | S | Short Free Text |
| TE / ML | T | Long Free Text |
| TE / ESTB | T | Essay Text Box |
| TE / FORM | Q | Multiple Short Text |
| Matrix / Likert | F | Array |
| Matrix / TE | ; | Array (Texts) |
| Matrix / Bipolar | 1 | Array Dual Scale |
| RO / DND | R | Ranking (Drag & Drop) |
| DB (all selectors) | X | Text Display |
| Slider / HSLIDER | N | Numerical Input |
| Slider / HBAR | N | Numerical Input |
| CS | K | Multiple Numerical |
| SBS | F | Side-by-Side → Array |
| PGR | R | Pick/Group/Rank |
| Timing | X | Display (no equivalent) |

Unmapped types default to `T` (Long Free Text) with a warning.

---

## Structure Mapping

| Qualtrics Concept | LimeSurvey Equivalent |
|---|---|
| Blocks | Question Groups |
| Survey Flow | Group ordering + relevance |
| Display Logic | Relevance equations |
| Piped Text `${e://...}` | `{VARNAME}` |
| Piped Text `${q://...}` | `{QuestionCode.NAOK}` |
| Embedded Data | URL parameters (manual setup) |
| ForceResponse = ON | mandatory = Y |
| Choice Randomization | Detected, flagged in report |
| Block Randomizers | Detected, flagged in report |
| Custom JavaScript | Not converted, flagged |

---

## Running from Source

Requires **Python 3.10+**. No external dependencies — stdlib only.

```bash
# Single file conversion
python source/convert.py input/survey.qsf -o output/survey.lss

# Batch conversion (all files in a folder)
python source/convert.py input/ -o output/

# With inspection report
python source/convert.py input/survey.qsf -o output/survey.lss --inspect

# Full application with reports and verification
python source/app.py

# Standalone inspection (analysis only, no conversion)
python source/qsf_inspector.py input/survey.qsf
```

---

## Importing into LimeSurvey

1. Log in to your LimeSurvey administration panel
2. Go to **Surveys > Create a new survey > Import**
3. Select the `.lss` file from the output folder
4. Click **Import**

After importing, review the following:

- Check all questions rendered correctly
- Verify display logic / relevance equations work
- Set up any embedded data fields as URL parameters (Survey settings > Panel integration)
- Review any questions flagged with warnings in the report
- Test the survey in preview mode before activating

---

## Known Limitations

- **Timing questions** have no LimeSurvey equivalent and are converted to display-only (`X`) placeholders
- **Custom JavaScript** in Qualtrics questions is not transferred; these questions need manual review in LimeSurvey
- **Complex nested boolean display logic** may produce simplified or approximate relevance equations with `FIXME` markers
- **Block randomizers** are detected but not fully translated to LimeSurvey randomization groups
- **Loop piped text** patterns produce `FIXME_LOOP_REF` placeholders for manual review
- **Question count differences** between input and output are expected — the converter skips Trash/Unused blocks and counts Matrix sub-items differently
- **Side-by-Side (SBS)** questions are converted to Array (`F`) as a best-effort approximation

---

## Troubleshooting

**"No .qsf files found"**
Make sure your files are in the `input/` folder and have the `.qsf` extension. The converter does not look in subfolders.

**Question count mismatch warning**
This is usually expected. The QSF inspector counts all question elements including those in Trash blocks, while the converter only processes active blocks.

**Mandatory count mismatch**
The converter only transfers `ForceResponse=ON`. Other Qualtrics validation types (content validation, regex) are noted in the report but may not have direct LimeSurvey equivalents.

**FIXME markers in converted survey**
Search the `.lss` file for `FIXME` to find expressions that need manual adjustment in LimeSurvey's ExpressionManager.

**Windows SmartScreen warning**
The `.exe` is not code-signed. Click "More info" then "Run anyway" to proceed.

---

## Security & Privacy

| | |
|---|---|
| **Fully Offline** | Runs 100% offline. No internet connection, no data sent to any server. All processing happens locally on your machine. |
| **No Data Collection** | Does not collect, store, or transmit any personal data, survey responses, or usage analytics. Your survey files never leave your computer. |
| **No External Dependencies** | Uses only the Python standard library. No third-party packages that could introduce supply chain risks or phone-home behavior. |
| **Local File Access Only** | Only reads from the `input/` folder and writes to the `output/` folder. Does not access any other files or directories on your system. |
| **Self-Contained Executable** | Built with PyInstaller, bundles a Python interpreter with the source code. No installation required, no files written outside the application folder. |
| **Source Code Included** | Full source code in the `source/` folder for transparency and auditability. Inspect, modify, or run directly with Python instead of the `.exe`. |
| **Suitable for Research Data** | Fully offline and local processing makes it suitable for sensitive research data and survey instruments under ethics board / IRB requirements. |

---

## Credits

| | |
|---|---|
| **Idea & concept** | Konrad Schweizer |
| **Implementation** | Claude Opus 4.8 (Anthropic) |

Python 3.10+ | stdlib only | no external dependencies
