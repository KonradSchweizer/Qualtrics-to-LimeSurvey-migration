# QSF2LSS

**Converts Qualtrics Survey Files (.qsf) to LimeSurvey Structure files (.lss) with full reporting and verification.**

*Formerly called QualtricsToLime. QSF2LSS is an independent, unofficial tool and is not affiliated with, endorsed by or sponsored by Qualtrics or LimeSurvey. The code was created with AI (Claude, by Anthropic). MIT-licensed, provided as-is without warranty.*

**🌐 Website, step-by-step demo and how it works: https://konradschweizer.github.io/Qualtrics-to-LimeSurvey-migration/**

Migrating surveys between platforms usually means rebuilding every question, answer option, and logic rule by hand — a tedious and error-prone process, especially for large or complex instruments. QSF2LSS automates this by transferring the common components (questions, groups, answer choices, display logic, validation, piped text) so you don't have to start from scratch. The tool analyses your Qualtrics survey, converts what it can, and clearly flags anything that needs manual attention, giving you a solid starting point instead of a blank canvas.

---

## Download

Grab the build for your operating system from the [**Releases page**](https://github.com/KonradSchweizer/Qualtrics-to-LimeSurvey-migration/releases):

| Your computer | Download |
|---|---|
| Windows | `QSF2LSS-Windows.zip` |
| Mac with Apple Silicon (M1/M2/M3/M4) | `QSF2LSS-macOS-AppleSilicon.zip` |
| Mac with Intel processor | `QSF2LSS-macOS-Intel.zip` |

> **Easiest on a Mac:** open Terminal, paste this line and press Enter. It downloads the right version into `~/Applications/QSF2LSS` and opens it, without Apple's "could not verify" warning (macOS only checks files downloaded by a browser):
> ```
> A=$([ "$(uname -m)" = arm64 ] && echo AppleSilicon || echo Intel); mkdir -p ~/Applications/QSF2LSS && curl -fL "https://github.com/KonradSchweizer/Qualtrics-to-LimeSurvey-migration/releases/latest/download/QSF2LSS-macOS-$A.zip" -o /tmp/QSF2LSS.zip && ditto -x -k /tmp/QSF2LSS.zip ~/Applications/QSF2LSS && open ~/Applications/QSF2LSS/QSF2LSS-GUI.app
> ```

> **Which Mac do I have?** Click the Apple menu () → **About This Mac**. If it says "Apple M1/M2/M3/M4" (or "Chip"), use the Apple Silicon build. If it says "Intel", use the Intel build.

Unzip the download anywhere you like, then follow the Quick Start below. See the [code signing policy](#code-signing-policy) for the status of signed builds.

Each download contains **two programs** that do exactly the same conversion:

| Program | Best for |
|---|---|
| `QSF2LSS-GUI` | Most users — a window where you pick or drag & drop `.qsf` files and read the results on screen |
| `QSF2LSS` | Scripting and batch runs — drop files in `input/`, run, collect from `output/`, no clicks needed |

---

## Quick Start

### Option A — the window (recommended)

1. Export your survey from Qualtrics as a `.qsf` file (see [Exporting from Qualtrics](#exporting-from-qualtrics) below)
2. Start the program:
   - **Windows:** double-click `QSF2LSS-GUI.exe`
   - **Mac:** double-click `QSF2LSS-GUI.app`. If Apple says it "could not verify" the app, see [Troubleshooting](#troubleshooting) (one-time fix).
3. Drag your `.qsf` files (or a whole folder) onto the window, or click **Add files…**
4. Optionally choose an output folder (**Change…**; by default the `.lss` lands next to each `.qsf`)
5. Press **Convert**. Each file gets a status line; click it to see the input analysis, the output summary and the verification checks
6. Import the `.lss` file into LimeSurvey (see [Importing into LimeSurvey](#importing-into-limesurvey) below)

### Option B — the folder-based converter

1. Export your survey from Qualtrics as a `.qsf` file
2. Place the `.qsf` file(s) in the `input/` folder
3. Run the converter:
   - **Windows:** double-click `QSF2LSS.exe`
   - **Mac:** double-click `QSF2LSS`. If Apple blocks it, see [Troubleshooting](#troubleshooting) (one-time fix).
4. Find your `.lss` files and conversion report in the `output/` folder
5. Import the `.lss` file into LimeSurvey

Both options run the same analysis, conversion and verification, and both write the same timestamped conversion report.

No Python installation or other software is required.

---

## Folder Structure

```
QSF2LSS/
|
|-- QSF2LSS-GUI.exe        The converter with a window (drag & drop)
|-- QSF2LSS.exe           The folder-based converter (input/ -> output/)
|-- README.md                     This file
|
|-- input/                        Place .qsf files here before running
|
|-- output/                       Results appear here after running
|   |-- *.lss                        Converted LimeSurvey files
|   |-- conversion_report_*.txt      Detailed report document
|
|-- source/                       Python source code
    |-- gui.py                       Window application entry point
    |-- app.py                       Folder-based application entry point
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

Requires **Python 3.10+**. The converter itself has no external dependencies — stdlib only.
The window version uses Tkinter (included with Python); drag & drop additionally needs
`pip install tkinterdnd2` (optional — without it the drop area becomes a click-to-browse area).

```bash
# Window application (drag & drop, on-screen results)
python source/gui.py

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

## Exporting from Qualtrics

To get a `.qsf` file from Qualtrics:

1. Log in to your Qualtrics account
2. Open the survey you want to export
3. Click the **three-dot menu (...)** next to the survey name, or go to **Survey Options**
4. Select **Export Survey**
5. Choose **QSF** (Qualtrics Survey Format) — this is the default
6. Click **Export** — a `.qsf` file will be downloaded to your computer
7. Move the downloaded `.qsf` file into the `input/` folder

> **Tip:** You can export multiple surveys and place them all in the `input/` folder at once. The converter will process them all in a single run.

> **Note:** The `.qsf` file contains only the survey structure (questions, logic, settings) — it does **not** include response data. Your collected responses stay safely in Qualtrics.

---

## Importing into LimeSurvey

To import the converted `.lss` file into LimeSurvey:

1. Log in to your LimeSurvey administration panel
2. On the home page, click **Create a new survey**
3. Switch to the **Import** tab at the top
4. Click **Browse** and select the `.lss` file from the `output/` folder
5. Click **Import survey**
6. LimeSurvey will show a summary of what was imported (groups, questions, answers)

### After importing — review checklist

- [ ] Open the survey and click through each question group to verify questions rendered correctly
- [ ] Check that answer options and subquestions are complete and in the right order
- [ ] Test display logic by previewing the survey and triggering the conditions
- [ ] Search the survey for `FIXME` — these mark expressions that need manual adjustment
- [ ] Set up embedded data fields as URL parameters (go to **Survey settings > Panel integration**)
- [ ] Review any questions flagged with warnings in the conversion report
- [ ] Preview the full survey from start to finish before activating
- [ ] If satisfied, activate the survey under **Survey settings > Overview > Activate this survey**

> **Tip:** Keep the conversion report (`output/conversion_report_*.txt`) as a reference while reviewing. It tells you exactly which questions have warnings and what to look out for.

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
Make sure your files are in the `input/` folder and have the `.qsf` extension. The folder-based converter does not look in subfolders (the window version does, when you drop a folder).

**The window version does not start / closes immediately**
Run `QSF2LSS.exe` (the console version) instead — it shows any error message on screen. Or run `python source/gui.py` from a terminal to see the full error.

**Question count mismatch warning**
This is usually expected. The QSF inspector counts all question elements including those in Trash blocks, while the converter only processes active blocks.

**Mandatory count mismatch**
The converter only transfers `ForceResponse=ON`. Other Qualtrics validation types (content validation, regex) are noted in the report but may not have direct LimeSurvey equivalents.

**FIXME markers in converted survey**
Search the `.lss` file for `FIXME` to find expressions that need manual adjustment in LimeSurvey's ExpressionManager.

**Windows SmartScreen warning**
The `.exe` is not code-signed. Click "More info" then "Run anyway" to proceed.

**macOS "Apple could not verify…" / "cannot be opened" warning**
The Mac build is not signed by Apple. Since macOS 15, right-click → Open no longer gets around this. Pick one:
- **Already downloaded:** click **Done**, then paste this into Terminal and open the app again. It removes the browser's download mark from the unzipped folder:
  ```
  xattr -dr com.apple.quarantine ~/Downloads/QSF2LSS-macOS-*
  ```
- **Fresh install without the warning:** use the one-line Terminal command in [Download](#download).
- **Without Terminal:** double-click the app and click **Done**. Then open **System Settings → Privacy & Security**, scroll down to **Security**, click **Open Anyway** next to "QSF2LSS-GUI was blocked", enter your password and click **Open**. The button is there for about an hour after the warning. Repeat for `QSF2LSS` if you use the console version.

---

## Security & Privacy

| | |
|---|---|
| **Fully Offline** | Runs 100% offline. No internet connection, no data sent to any server. All processing happens locally on your machine. |
| **No Data Collection** | Does not collect, store, or transmit any personal data, survey responses, or usage analytics. Your survey files never leave your computer. |
| **No External Dependencies** | The converter uses only the Python standard library. The window version bundles one extra component for drag & drop, [tkdnd](https://github.com/petasis/tkdnd) via `tkinterdnd2` — an open-source Tk extension that only handles the drop events; it has no network code. The console version has no third-party code at all. |
| **Local File Access Only** | The console version only reads from the `input/` folder and writes to the `output/` folder. The window version reads the `.qsf` files you choose and writes to the output folder you choose. Nothing else on your system is touched. |
| **Self-Contained Executable** | Built with PyInstaller, bundles a Python interpreter with the source code. No installation required, no files written outside the application folder. |
| **Source Code Included** | Full source code in the `source/` folder for transparency and auditability. Inspect, modify, or run directly with Python instead of the `.exe`. |
| **Suitable for Research Data** | Fully offline and local processing makes it suitable for sensitive research data and survey instruments under ethics board / IRB requirements. |

---

## Code signing policy

Windows releases are being set up for free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org). The application is still pending, so current downloads are unsigned. Once signing is active, every signed file is built automatically from this repository's source code by [GitHub Actions](.github/workflows/build.yml), and each release is approved by hand before it is signed.

- **Committers and reviewers:** [Konrad Schweizer](https://github.com/KonradSchweizer)
- **Approvers:** [Konrad Schweizer](https://github.com/KonradSchweizer)

**Privacy:** this program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it. It has no network functionality at all.

The same policy is on the [website](https://konradschweizer.github.io/Qualtrics-to-LimeSurvey-migration/#signing).

---

## Credits

| | |
|---|---|
| **Idea & concept** | Konrad Schweizer |
| **Implementation** | Claude Opus 4.8 (Anthropic) |

Python 3.10+ | converter: stdlib only | window version: Tkinter + optional tkinterdnd2 for drag & drop
