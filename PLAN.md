# Claimline build plan (Claude Code edition)

**Project 1 of 3. Build window: 16 November to 27 December 2026, with 28 December to 3 January as buffer.**
Revised 16 November 2026. This file replaces the Claimline section and kickoff prompt of the original three-project plan.

Claimline turns daily war reporting into a queryable ledger of events in which every record keeps who claimed it, the exact words it rests on, and whether it was later confirmed.

## How to use this file

1. Do the setup in section 9 once.
2. Save this file in the repo root as `PLAN.md`.
3. Work through the milestone prompts in section 11, one fresh Claude Code session each.
4. After each milestone, run `/milestone`, then `/quiz`.

Sections 1 to 8 are the specification. Claude Code reads them from `PLAN.md` when a prompt tells it to.

## 1. The question

**How often are battlefield claims later confirmed, and how fast?**

Daily reporting on Ukraine is prose. ISW publishes an assessment every day, and Ukraine's General Staff publishes daily operational updates. An analyst who wants to know which claimed advances were later confirmed has to re-read weeks of text. Existing event datasets code what happened and where. The claim layer (who said it, with what evidence) is not a first-class field. Keeping that layer is where source criticism becomes a technical advantage.

Hypotheses, fixed before any code:

- **H1.** A schema-constrained LLM with a verification pass reaches event F1 of 0.80 or better against hand labels, and beats a single-prompt LLM by at least 8 points.
- **H2.** Fewer than half of Russian-claimed advances are confirmed by geolocated evidence within 14 days in ISW's own reporting.

Headline numbers: event F1 on a hand-labelled test set, and the share of claimed advances confirmed at 7, 14 and 30 days.

What this cannot claim: it measures confirmation inside ISW's reporting, not ground truth. That sentence goes in the README and in the finding.

## 2. What changed from the original plan

| Original | Problem | Now |
| --- | --- | --- |
| Annotate 45 whole reports | An ISW daily can hold 80 or more events. 30 in full is roughly 2,500 events and 50+ hours, against a 700-event target. | Sampling unit is a report section. 2 pre-assigned sections per ISW report, General Staff reports in full. |
| One linking rule: 5 km and 3 days | A confirmation on day 10 can never join a cluster that closes on day 3, yet lag is reported at 7, 14 and 30 days. | Two rules: a duplicate rule and a separate confirmation rule (section 5). |
| 90-day corpus | Claims in the last 30 days have not had 30 days to be confirmed. | 120-day corpus. Claims are analysed from the first 90 days only. |
| Model outputs character offsets | Language models count characters badly. | Model returns the exact quote. Code finds it and computes offsets. No match, no record. |
| Russian MoD as optional third corpus | Geo-blocked and unreliable. | Dropped. Russian claims are taken from ISW's reporting of them. |
| "Haiku-class" and "Sonnet-class" | Unpinned. | `claude-haiku-5-5` for extraction. Verifier tested on both `claude-haiku-5-5` and `claude-sonnet-5-5`. |
| Event unit not defined | "Attacked near A, B and C on 14 and 15 November" is one event or six. | One event per place per day. Written into SPEC. |
| Matching not defined | One prediction could match several gold events. | One-to-one matching, closest valid pair first. |
| ISW terms "to be checked" | Still unverified as of 16 November. | Read the terms and email for permission in week 1 (section 3). |
| Chat kickoff prompt | Written for a chat window. | `CLAUDE.md`, skills, and one Claude Code prompt per milestone. |

## 3. Data

| Source | Use | Access and notes |
| --- | --- | --- |
| ISW Russian Offensive Campaign Assessment, daily | Primary corpus, 120 consecutive days | https://understandingwar.org . Mirror with the same text: https://www.criticalthreats.org/analysis/russian-offensive-campaign-assessment-september-2-2026 (URL pattern example). Each report states its data cutoff time. Store it. |
| Ukrainian General Staff daily operational update | Second corpus, same 120 days, Ukrainian | https://armyinform.com.ua republishes each report as text. Do not scrape Facebook. Check ArmyInform's terms too. |
| VIINA | External comparison: daily event counts by oblast | https://github.com/zhukovyuri/VIINA . Has 2026 event files. |
| ACLED | External comparison, older months only | https://acleddata.com . Research tier has a 12-month delay. Optional. |
| GeoNames Ukraine dump | Gazetteer | https://download.geonames.org/export/dump/ , file `UA.zip`. Includes alternate names. |
| OpenStreetMap extract, Ukraine | Gazetteer aliases | https://download.geofabrik.de/europe/ukraine.html . Place nodes carry `name:uk`, `name:ru`, `name:en`. |

**Corpus window.** Reports dated 19 July 2026 to 15 November 2026 (120 days). Claims are analysed from 19 July to 16 October (the first 90 days). The last 30 days exist only to observe confirmations.

**Permission.** Before collecting, read the terms in ISW's site footer. Then email press@understandingwar.org. Say what you are building, that you store text locally and never republish it, and that you publish only derived records, source URLs and character offsets. Keep the reply in the repo as `docs/permissions.md`. If the answer is no, use the General Staff corpus plus a smaller hand-copied ISW sample for evaluation only, and say so in the README.

**Collection rules.** One request every few seconds. Save raw HTML and a cleaned text version to `data/raw/` and `data/text/`, both git-ignored. Store a SHA-256 of each cleaned text file so offsets can be checked later.

## 4. Gold set

- **Unit:** one report section (one axis or front, for example the Pokrovsk direction).
- **Sample:** 30 ISW reports spread evenly across the 120 days, 2 sections each. The sections are assigned by a fixed rotation over the list of axes, written into `SPEC.md` before you read the text. Plus 15 General Staff reports, in full.
- **Target:** at least 700 events. If you fall short, add sections using the same rotation. Do not choose sections by hand.
- **Split by date:** the earliest 10 reports are dev. The later 35 are test.
- **Consistency:** re-label the sections of 6 reports after a 14-day gap and report Cohen's kappa on type and status. This measures your own consistency. There is no second annotator, and the README says so.
- **Guideline:** 3 to 5 pages, written before labelling and revised once after a 5-section pilot. It is a deliverable.
- **Tool:** Label Studio, run locally.

**The rule that protects the project:** label test sections before any model has been run on those reports, and never start test labels from model output. Claude Code is blocked from reading `eval/gold/test/` by a deny rule (section 9).

## 5. Schema, pipeline and models

### Schema, one row per event

| Field | Type | Rule |
| --- | --- | --- |
| `event_type` | enum, 12 values | ground_assault, territorial_advance, withdrawal, missile_strike, drone_strike, air_strike, shelling, air_defence_interception, force_movement, logistics_or_infrastructure_strike, naval_event, other |
| `epistemic_status` | enum, 5 values | ru_claimed, ua_claimed, third_party_claimed, geolocated_confirmed, analyst_assessed |
| `claim_source` | string, nullable | Who made the claim as the text names them, for example "Russian MoD" or "milblogger" |
| `actor`, `target` | enum plus free text | RU, UA, other |
| `location_text`, `lat`, `lon`, `gazetteer_id` | string, floats, id | `location_text` must appear verbatim in the evidence quote |
| `geo_precision` | 1, 2 or 3 | 1 settlement, 2 direction or area, 3 oblast |
| `event_date`, `report_date` | dates | Event date may precede report date |
| `units` | list | Name, echelon, branch, resolved to an alias table |
| `equipment`, `quantity` | list, integer | Numbers must appear verbatim in the evidence quote |
| `evidence_quote` | string | Internal only. Never published. |
| `evidence_start`, `evidence_end` | integers | Computed by code from the quote. Offsets into the cleaned text. |
| `text_sha256` | string | Hash of the cleaned source text the offsets refer to |
| `source_url`, `footnote_ref` | strings | Traceability |

The fields map onto SALUTE (Size, Activity, Location, Unit, Time, Equipment).

**Event unit.** One event per place per day. "Russian forces attacked near A, B and C on November 14 and 15" is six events sharing one evidence quote.

### Pipeline

| Step | What it does | Model |
| --- | --- | --- |
| 1. Segment | Split each report by section headings and axis names. | None |
| 2. Extract | One call per section. Structured output. Returns events with `evidence_quote`. | `claude-haiku-5-5` |
| 3. Verify, deterministic | Find the quote in the text and compute offsets. Reject the record if the quote is missing, or if the location string or any number is not inside it. | None |
| 4. Verify, model | A separate call sees only the quote and the record and answers per field: supported or not. Unsupported fields are dropped. | `claude-haiku-5-5` and `claude-sonnet-5-5`, both scored on dev. Ship the cheaper unless Sonnet lowers the unsupported-field rate by a margin you can state. |
| 5. Geocode | Match against the gazetteer. Disambiguate by oblast named in the section, then distance to the previous day's events on the same axis, then population. | None. For names still ambiguous, one Sonnet call may choose among candidate rows. It never outputs coordinates. |
| 6. Resolve units | Fuzzy match against an alias table you grow from the data. | None at run time |
| 7a. Link duplicates | Same type, within 5 km and 3 days, from any source, form one cluster. | None |
| 7b. Link confirmations | For each `ru_claimed` or `ua_claimed` territorial_advance, find the first `geolocated_confirmed` record for the same settlement and actor, dated from the claim date up to 30 days later. Lag is the gap in days. | None |

### Baselines, all in one ablation table

| System | What it is |
| --- | --- |
| B0 | Regex verbs plus gazetteer lookup, no model |
| B1 | GLiNER2 zero-shot entities plus rules. `fastino/gliner2-base-v1` for English, `fastino/gliner2-multi-v1` for Ukrainian |
| B2 | Single-prompt `claude-haiku-5-5`, free-form JSON, no schema, no verification |
| S1 | Schema-constrained extraction |
| S2 | S1 plus deterministic verification |
| S3-H | S2 plus Haiku verifier and geocoder disambiguation |
| S3-S | S2 plus Sonnet verifier and geocoder disambiguation |

B2 and S1 use the same model on purpose. The table then isolates the method.

### Claude API settings

- **Structured output.** Pass the Pydantic class to `client.messages.parse(..., output_format=Event)`. Docs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- **Schema limits.** No enforced number ranges or string lengths. At most 24 optional fields and 16 union-type fields per request. Enum capitalisation is not guaranteed. Compare enums case-insensitively and validate ranges in Pydantic after parsing.
- **Citations cannot be combined with structured output.** The API returns a 400 error. This is one more reason for the quote-then-offset design.
- **Model IDs.** `claude-haiku-5-5` and `claude-sonnet-5-5`. Check https://platform.claude.com/docs/en/models/overview for a dated snapshot ID and pin that in `config.yaml` if one is listed.
- **Effort.** Both models use adaptive thinking with an effort setting. Set it explicitly in `config.yaml`, log it with every run, and test low against medium on dev for extraction.
- **Batch API** for the full 120-day run: half price, works with structured output. Live calls while developing. Docs: https://platform.claude.com/docs/en/build-with-claude/batch-processing
- **Prompt caching.** Fixed instructions and examples first, section text last. Changing the schema invalidates the cache, so freeze the schema before the big run. Docs: https://platform.claude.com/docs/en/build-with-claude/prompt-caching

### Prices (USD per million tokens, checked 16 November 2026)

| Model | Input | Output | Batch input / output |
| --- | --- | --- | --- |
| Claude Haiku 5.5, prompts up to 100K tokens | 0.10 | 0.50 | 0.05 / 0.25 |
| Claude Sonnet 5.5 | 2 | 10 | 1 / 5 |

Source: https://platform.claude.com/docs/en/about-claude/pricing

My estimates, to be replaced by your measured numbers: extraction costs about one cent per ISW report on Haiku. Sonnet verification of about 100 records costs near 0.18 per report, or 0.09 through Batch. The whole project should cost under 30 dollars including reruns. Set a monthly spend limit in the Console anyway.

## 6. Metrics and targets

All go into `SPEC.md` before pipeline code.

| Metric | Definition | Target |
| --- | --- | --- |
| Event F1 | One-to-one matching. A predicted event matches a gold event if type is equal, dates are within 1 day and locations within 10 km. Closest valid pair first, each gold event used once. | 0.80 or better |
| F1 sensitivity | Same, at 5, 10 and 25 km and at 0, 1 and 2 days | Report the grid |
| Epistemic status accuracy | On matched events | 0.90 or better |
| Geocoding accuracy@10 km | On precision-1 locations | 0.90 or better, median error in km reported |
| Quantity exact match | On matched events with numbers | 0.95 or better |
| Unsupported-field rate | Share of output fields you judge not supported by the quote, on 200 sampled records | Below 2% |
| Verifier cost in recall | Recall of S1, S2 and S3 side by side | Report it |
| Annotator consistency | Cohen's kappa on 6 re-labelled reports, type and status | 0.75 or better |
| External validity | Spearman correlation of daily event counts by oblast against VIINA | Report it, no target |
| Cost and speed | Euros and seconds per report | Below 0.10 euros and 60 seconds |
| H2 | Share of Russian-claimed advances (first 90 days) confirmed at 7, 14 and 30 days, and median lag per axis | Report with 95% interval |

Bootstrap intervals resample whole reports, not single events. Events inside one report are not independent.

## 7. Deliverables

- The ledger as Parquet (without `evidence_quote`), the JSON Schema, and the annotation guideline
- The ablation table with confidence intervals
- A map and timeline demo with a filter for epistemic status and a 48-hour delay
- `FAILURES.md` with the five worst errors
- The finding, 1,200 words: "Claimed versus confirmed: 90 days of advances on the Ukrainian front"
- A 90-second screen recording and a LinkedIn post

## 8. Shared standards

All three projects share one stack and one set of rules, so a reviewer who opens any repo sees the same discipline.

| Layer | Choice | Why |
| --- | --- | --- |
| Language and packaging | Python 3.12, `uv`, `ruff`, `pytest`, a `Makefile` | One-command reproducibility |
| Storage | Parquet files queried with DuckDB | No server, fast on a laptop, easy to publish |
| Schemas | Pydantic models, exported as JSON Schema | The schema is the contract and a portfolio artefact |
| Scheduling | GitHub Actions | Free for public repos |
| Front end | Static site, MapLibre GL, same dark style as Providence | Free hosting, visual continuity |
| Config | `config.yaml` holds model IDs, dates and thresholds | Every eval run logs the config it used |

Repo layout:

```
README.md        case study: question, method, result, limits
PLAN.md          this file
CLAUDE.md        standing instructions for Claude Code
SPEC.md          schema, metric definitions, numeric targets (written before code)
DECISIONS.md     one line per design choice and the reason
FAILURES.md      worst errors, with examples
Makefile         make data / make eval / make site / make all
config.yaml      model IDs, dates, thresholds
src/             pipeline code
eval/            gold data, splits, scoring scripts, results.csv
notebooks/       one notebook per finding
site/            static demo
.claude/         settings.json and skills
```

Evaluation rules:

1. Write `SPEC.md` with metric definitions and numeric targets before any pipeline code. Commit it. The commit date proves the targets were not fitted afterwards.
2. Split by time, never at random.
3. Tune only on the dev split. Score the test split once per release and record every run in `eval/results.csv` with commit hash, config and date.
4. Report a 95% bootstrap confidence interval on every headline number.
5. A missed target stays in the README with an explanation.

Ethics and OPSEC rules:

- Public sources only. No leaked material, no private Telegram scraping, no personal data about individual soldiers or crew.
- Respect each source's terms. Store copyrighted text locally and never commit it. Publish derived records, source URLs and character offsets only.
- A 48-hour delay on anything that shows conflict events on a map.
- Publish aggregates, never individual aircraft tracks. Attribute interference to a state only by quoting official sources.
- Every README carries a limits section and a line on intended use.

The bar before the project goes on your CV:

- A public repo that runs end to end from `make all` on a clean machine
- A frozen test or validation set, with the freeze date in the README
- At least two baselines, one of them with no AI, in the same results table as your system
- `FAILURES.md` with the five worst errors, examples and causes
- A live demo link and a 90-second screen recording
- One written finding of 1,000 to 1,500 words that a non-technical analyst could use
- You can answer every "Defend it" question in this file without notes

## 9. Setup

### Accounts

| Account | Used for | Note |
| --- | --- | --- |
| GitHub | Repo, Actions, Pages | Make the repo public from day one. The commit history is evidence. |
| Claude plan that includes Claude Code | Writing the code with you | The free claude.ai plan does not include Claude Code. Pro or above does. |
| Anthropic Console (API key) | The pipeline's own model calls | Billed separately from your Claude plan. Create a key and set a monthly spend limit. |

### Install on your machine

Run these once. Install commands for Claude Code are taken from the setup page as summarised on 16 Nov 2026. Confirm them at https://code.claude.com/docs/en/setup before running.

```bash
# Claude Code (macOS, Linux, WSL)
curl -fsSL https://claude.ai/install.sh | bash
# Windows PowerShell alternative:  irm https://claude.ai/install.ps1 | iex

claude --version
claude doctor

# uv (Python and package manager)  https://docs.astral.sh/uv/
curl -LsSf https://astral.sh/uv/install.sh | sh

# GitHub CLI, optional but useful for Actions and releases  https://cli.github.com
```

On Windows, work inside WSL. `make` and the shell commands in this plan assume a Unix shell.

### Create the repo

```bash
mkdir claimline && cd claimline
git init
uv init --python 3.12
mkdir -p src eval notebooks site .claude/skills/quiz .claude/skills/milestone
cp /path/to/this/file PLAN.md
```

Then create these files by hand, with the contents given in this plan:

1. `CLAUDE.md` (section "CLAUDE.md")
2. `.claude/settings.json` (below)
3. `.claude/skills/quiz/SKILL.md` and `.claude/skills/milestone/SKILL.md` (below)
4. `.gitignore` (below)

### `.claude/settings.json`

Allow rules stop Claude Code asking permission for routine commands. Deny rules are hard blocks.

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(uv run *)",
      "Bash(uv sync)",
      "Bash(uv add *)",
      "Bash(make lint)",
      "Bash(make test)",
      "Bash(make eval)",
      "Bash(make site)",
      "Bash(git status)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(make data)"
    ],
    "ask": [
      "Bash(make eval-test)",
      "Bash(git push *)"
    ],
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./eval/gold/test/**)"
    ]
  }
}
```

The `Read` deny rule stops Claude Code opening test labels with its file tools. It does not stop a shell command from reading them, so the rule in `CLAUDE.md` matters too. `make eval-test` sits under `ask`, so it always needs your explicit approval. If a rule does not behave as expected, run `/permissions` inside Claude Code to see the active rules. Reference: https://code.claude.com/docs/en/settings

### `.gitignore`

```
.env
.venv/
__pycache__/
data/raw/
data/text/
data/*.parquet
*.sqlite
.label-studio/
.claude/settings.local.json
```

### Skills

A skill is a saved prompt you run by typing `/name`. Both of these set `disable-model-invocation: true`, so they only run when you type them.

`.claude/skills/quiz/SKILL.md`

```markdown
---
name: quiz
description: Quiz the user on what was just built. Run after every milestone.
disable-model-invocation: true
---
Look at the commits since the last tag or the last quiz entry in DECISIONS.md.
Ask me three questions about the mechanism of what we just built: why it works,
what would break it, and what the alternative was. One question at a time.
Wait for my answer before the next one.
Correct me bluntly and specifically. Do not soften wrong answers.
If I get one wrong, explain it, then ask a second question on the same mechanism.
When I have answered all three correctly without help, append a dated line to
DECISIONS.md for each decision we discussed (decision, reason, alternative rejected).
Do not start the next milestone until this is done.
```

`.claude/skills/milestone/SKILL.md`

```markdown
---
name: milestone
description: Close out a milestone. Lint, test, record results, commit.
disable-model-invocation: true
---
1. Run `make lint` and `make test`. Fix failures before going on.
2. If this milestone produced dev-set or validation numbers, append them to
   eval/results.csv with the commit hash, the config values used and today's date.
3. Check the "Done when" list for the current milestone in PLAN.md. List each
   item as done or not done. Do not mark anything done that you have not verified
   by running it.
4. Update README.md only if a result or a limit changed.
5. Commit with a message that starts with the milestone number.
6. Tell me what is left, what you were unsure about, and any place where you
   departed from SPEC.md. Then stop and tell me to run /quiz.
```

### First session check

```bash
claude
```

Inside Claude Code, run `/context` and confirm `CLAUDE.md` is listed under memory files. If it is, you are ready for the first milestone prompt.

### Project-specific setup

```bash
uv add anthropic pydantic duckdb pyarrow polars httpx beautifulsoup4 lxml rapidfuzz scikit-learn pyyaml python-dotenv
uv add gliner2            # baseline B1, https://github.com/fastino-ai/GLiNER2
uv add --dev pytest ruff
uv tool install label-studio   # or: pip install label-studio in a separate environment
```

Put the API key in `.env` as `ANTHROPIC_API_KEY=...`. The pipeline loads it with `python-dotenv`. Do not export it in your shell.

Folder convention for gold data:

```
eval/gold/dev/     dev labels, Claude Code may read
eval/gold/test/    test labels, Claude Code may NOT read (deny rule)
```

## 10. CLAUDE.md

Save this as `CLAUDE.md` in the repo root.

````markdown
# Claimline

Battlefield report extractor. Turns ISW and Ukrainian General Staff daily reports
into a ledger of events with claim source, evidence offsets and confirmation status.
The full specification is in PLAN.md. Metric definitions and targets are in SPEC.md.
SPEC.md wins over PLAN.md if they disagree. Tell me when they do.

## Commands
- `make lint`   ruff check and format
- `make test`   pytest
- `make data`   collect and clean the corpus (slow, network)
- `make eval`   score all systems on the DEV split
- `make site`   build the static demo
- `uv run python -m src.<module>` to run one stage

## Hard rules
- Never read, print, summarise or copy anything under eval/gold/test/. Only
  `eval/score.py` may open those files, and only via `make eval-test`.
- Never run `make eval-test` unless I type the words "run the test set" in this session.
- Never commit anything under data/raw/ or data/text/. Source text stays local.
- Published outputs never contain `evidence_quote` or any source text. Offsets,
  hashes and URLs only.
- The model never produces character offsets or coordinates. Code computes offsets
  from the quote. Coordinates come from the gazetteer.
- Few-shot examples and prompt tuning use dev data only.
- Model IDs, effort and thresholds live in config.yaml. No model ID in code.
- Every eval run appends a row to eval/results.csv: commit hash, config, date, split.
- Do not change a metric definition or target in SPEC.md. If one looks wrong, stop and tell me.
- Do not add a dependency without saying why.

## How to work with me
- Start each milestone by reading its section in PLAN.md and SPEC.md, then propose
  a plan before writing code.
- Make decisions yourself and keep moving. Do not ask me to approve each step.
  Stop and ask only when a choice cannot be undone or contradicts SPEC.md.
- Write a pytest test with every function. Small functions, type hints, no notebooks
  for pipeline code.
- Before saying something works, run it and show me the output.
- When a milestone is finished, tell me to run /milestone and then /quiz.
- I am learning. When you use a technique I may not know, explain the mechanism in
  two or three sentences, once.

## Python
Python 3.12, uv, ruff, pytest, Pydantic v2, DuckDB over Parquet. Anthropic SDK with
`client.messages.parse` and a Pydantic output format for all structured calls.
````

## 11. Milestone prompts for Claude Code

Paste one prompt per fresh session. Each ends with a "Done when" list that `/milestone` checks.

### Milestone 1, week 1 (16 to 22 November): spec, guideline, collector

```text
Milestone 1 of Claimline. Read PLAN.md sections 1 to 6. There is no SPEC.md yet.

Propose a plan first, then do this in order:

1. Write SPEC.md. It must contain: the schema from PLAN.md section 5 as a Pydantic
   model plus exported JSON Schema; the event-unit rule (one event per place per
   day); the one-to-one matching algorithm in pseudocode; both linking rules; every
   metric and numeric target from section 6; the corpus window and the 90-day
   analysis window; the gold-set sampling design with the fixed section rotation
   written out as a table of (report date, section names). Use a seeded shuffle of
   the axis list so I cannot pick sections by hand. Commit SPEC.md alone, before
   any pipeline code.
2. Draft docs/annotation_guideline.md, 3 to 5 pages: definitions for all 12 event
   types and 5 statuses, the trigger phrases for each status, geo precision rules,
   and a "hard cases" section with empty slots I will fill after the pilot.
3. Build src/collect.py: fetch reports for the corpus window from the sources in
   PLAN.md section 3, one request every 3 seconds, save raw HTML to data/raw/ and
   cleaned text to data/text/, write a manifest (date, source, url, sha256, data
   cutoff time if stated). Before fetching anything, check each site's robots.txt
   and show me what it allows. Fetch 3 reports per source as a test and stop.
4. Build src/segment.py: split a cleaned report into sections by heading. Test it
   on the 3 fetched ISW reports and print the section names it found.
5. Write the Label Studio labelling config for span labelling where each span is an
   evidence quote with attributes for event_type, epistemic_status, actor,
   location_text, event_date and quantity. Write a script that exports my labels to
   eval/gold/dev/ or eval/gold/test/ according to the date split in SPEC.md.
6. Set up the Makefile targets, .gitignore, config.yaml and a passing pytest run.

Done when:
- SPEC.md is committed in its own commit, earlier than any file in src/
- 3 reports per source are collected and segmented, with tests passing
- Label Studio starts with the config and loads one section
- make lint and make test pass
```

Your own work this week, outside Claude Code: send the ISW permission email, read 5 ISW and 5 General Staff reports end to end, label 5 pilot sections, and fill the hard-cases section of the guideline.

### Milestone 2, week 2 (23 to 29 November): gold set, gazetteer, B0 and B1

```text
Milestone 2 of Claimline. Read SPEC.md and PLAN.md sections 4 and 5.
Do not read anything under eval/gold/test/.

Propose a plan first, then:

1. Run the full collection for the corpus window. Report how many days are missing
   per source and log them in data/manifest.
2. Build src/gazetteer.py: load the GeoNames UA dump and the OSM Ukraine place
   nodes, merge them into one Parquet table with a stable gazetteer_id, lat, lon,
   oblast, population and an alias list (Ukrainian, Russian, English, and old
   names where the sources give them). Add a lookup function with exact then fuzzy
   matching. Test it on 30 place names taken from eval/gold/dev/.
3. Build B0 in src/baselines/b0_regex.py: verb patterns for each event type plus
   gazetteer lookup, no model.
4. Build B1 in src/baselines/b1_gliner.py: GLiNER2 zero-shot entities (settlement,
   military unit, equipment, date) plus rules that assemble events.
5. Build eval/score.py implementing the matching algorithm exactly as SPEC.md
   states it. Unit-test it on five hand-made cases that I can read: a perfect
   match, a 12 km miss, a 2-day miss, two predictions for one gold event, and a
   type mismatch. Add bootstrap intervals that resample whole reports.
6. Score B0 and B1 on dev and append to eval/results.csv.

Done when:
- The gazetteer resolves at least 27 of the 30 dev place names
- eval/score.py passes its five hand-made tests
- B0 and B1 have dev rows in eval/results.csv with intervals
```

Your own work this week: finish labelling. Lock the test labels (commit them, note the date in the README) before milestone 3 starts.

### Milestone 3, week 3 (30 November to 6 December): B2, S1, S2

```text
Milestone 3 of Claimline. Read SPEC.md and PLAN.md section 5, including the Claude
API settings. Do not read anything under eval/gold/test/.

Propose a plan first, then:

1. Build src/extract.py. One call per section with client.messages.parse and the
   Pydantic Event list as output format. The prompt has fixed instructions and 3 to
   5 worked examples from dev first (include one section with zero events), then
   the report date, section name and section text last. The model returns
   evidence_quote, never offsets or coordinates. Model ID and effort come from
   config.yaml.
2. Build B2 in src/baselines/b2_single_prompt.py: same model, one free-form prompt
   asking for JSON, no schema, no examples beyond one. Parse defensively.
3. Build src/verify_det.py: normalise whitespace and quote characters on both
   sides, find the quote in the section text, compute evidence_start and
   evidence_end, and reject the record if the quote is missing or if location_text
   or any number is not inside it. Count rejections by reason.
4. Score B2, S1 and S2 on dev. Report precision and recall separately, plus cost in
   USD and seconds per report from the API usage fields.
5. Show me the 10 dev events S1 missed and the 10 it invented, with their quotes.

Done when:
- The ablation table has five rows on dev: B0, B1, B2, S1, S2
- Rejection counts by reason are in the README draft
- Cost and seconds per report are measured, not estimated
```

### Milestone 4, week 4 (7 to 13 December): verifier, geocoder, units

```text
Milestone 4 of Claimline. Read SPEC.md and PLAN.md section 5.
Do not read anything under eval/gold/test/.

Propose a plan first, then:

1. Build src/verify_model.py. A separate call that receives only the evidence quote
   and the record, and returns supported or not for each field. Unsupported fields
   are set to null. If event_type or location is unsupported, drop the record. Make
   the verifier model a config value.
2. Run it twice on dev, once with claude-haiku-5-5 and once with claude-sonnet-5-5.
   Report recall, precision, cost and the fields each one removed.
3. Build geocoder disambiguation in src/geocode.py with the fixed rule order from
   PLAN.md: oblast named in the section, distance to the previous day's events on
   the same axis, population. Log which rule decided each case. For names still
   ambiguous, add an optional model call that chooses among candidate rows only.
4. Build src/units.py: fuzzy match unit names to data/unit_aliases.csv. Write a
   script that proposes new alias merges into a review file. I approve them by hand.
5. Build the sampling script for the unsupported-field audit: 200 random records
   from dev-period reports that are NOT in the gold set, shown as quote plus fields
   in a CSV I can mark up.
6. Score S3-H and S3-S on dev.

Done when:
- S3-H and S3-S rows are in eval/results.csv
- The 200-record audit file exists and I have marked it
- Geocoding accuracy@10 km and median error are reported on dev
```

### Milestone 5, week 5 (14 to 20 December): linking, the finding, the test run

```text
Milestone 5 of Claimline. Read SPEC.md and PLAN.md sections 5 and 6.
Do not read anything under eval/gold/test/.

Propose a plan first, then:

1. Run the chosen system over the full 120-day corpus using the Message Batches
   API. Write the ledger to data/ledger.parquet.
2. Build src/link.py with both rules from SPEC.md: 7a duplicate clusters in DuckDB,
   7b confirmation links. For 7b, restrict claims to the first 90 days and look for
   confirmations up to 30 days later.
3. Build notebooks/01_claimed_vs_confirmed: share of Russian-claimed advances
   confirmed at 7, 14 and 30 days with bootstrap intervals, and median lag per
   axis. Build notebooks/02_viina: Spearman correlation of daily event counts by
   oblast against VIINA.
4. Add the `make eval-test` target. It runs eval/score.py on the test split for all
   systems, appends to eval/results.csv, and writes eval/test_run.json with commit
   hash, config and timestamp. It refuses to run if eval/test_run.json exists.
5. Stop here and wait. Do not run it.

After I type "run the test set":
6. Run make eval-test once. Build the final ablation table with intervals and the
   F1 sensitivity grid.
7. Draft FAILURES.md from DEV errors and the test-set aggregate numbers only: the
   five worst error patterns, each with an example quote from dev, the cause, and
   what would fix it.

Done when:
- eval/test_run.json exists and the test rows are in eval/results.csv, once
- H1 and H2 are each answered with a number and an interval in the README
- Every missed target is listed in the README with an explanation
```

### Milestone 6, week 6 (21 to 27 December): site, finding, release

```text
Milestone 6 of Claimline. Read PLAN.md sections 7 and 8.

Propose a plan first, then:

1. Build the static site in site/: a MapLibre GL map of the ledger with a filter
   for epistemic status and event type, a timeline, and a panel showing claim and
   confirmation pairs. Dark style. Exclude anything dated within 48 hours of build
   time. The site reads a published Parquet or GeoJSON file that contains no source
   text.
2. Export the public ledger without evidence_quote, the JSON Schema and a data
   dictionary.
3. Make `make all` run end to end. Test it from a fresh clone in a temporary
   directory with only the public files and a stub for the private corpus, and show
   me the output.
4. Write the README as a case study: question, method, result table, limits,
   intended use, how to reproduce. Lead with the result.
5. Give me an outline for the 1,200-word finding with the numbers filled in. I
   write the prose.
6. Set up GitHub Pages deployment for site/.

Done when:
- make all passes from a fresh clone
- The site is live and shows no event newer than 48 hours
- README, SPEC.md, FAILURES.md, DECISIONS.md and the guideline are all in the repo
```

Your own work this week: write the finding, record the 90-second walkthrough, post it.

## 12. Technique tips

### Labelling

- **Never pre-label test sections with a model.** You will anchor on its answers and F1 will flatter the system. Pre-labelling is acceptable for dev only.
- **Write the guideline around hard cases.** Collect 15 to 20 awkward sentences during the pilot and record a ruling for each: "continued attacks" with no date, "unspecified positions", a claim ISW reports and doubts in the same sentence, advances "northwest of" a town.
- **Status follows the wording, not your judgement.** "Geolocated footage published on [date] indicates" is `geolocated_confirmed`. "Russian milbloggers claimed" is `ru_claimed`. "ISW assesses" is `analyst_assessed`.
- **Log minutes per section.** Minutes per event is a number worth reporting.

### Extraction

- **One call per section, not per report.** Shorter input means fewer skipped events.
- **Pass the report date in the prompt** so "on November 14 and 15" resolves to real dates.
- **Let the model say `other` and null.** A forced location is a fabricated location.
- **Include one zero-event example**, so an empty list is a valid answer.

### Verification

- **The model verifier gets less context on purpose.** If it sees the whole section it will confirm fields from text the evidence does not contain.
- **Report what verification costs in recall.** The interview question is whether the trade is worth it, and you need the number.

### Geocoding

- **Build aliases before you geocode.** One settlement can appear under a Ukrainian name, a Russian name, a transliteration of each, and a pre-renaming name.
- **"Near", "toward" and "in the direction of" are precision 2**, not a settlement point.

### Evaluation

- **Fix the matching code before you see any scores.**
- **One test run.** Commit hash, model IDs, effort and date go next to the numbers.
- **For lag, a claim whose window is not over is censored.** The 120-day corpus handles the 30-day case. Say so in the method.

### Working with Claude Code

- **One milestone, one session.** Start a fresh session (`/clear` or a new `claude`) for each milestone prompt. Long sessions drift from the spec, and `CLAUDE.md` reloads cleanly each time.
- **Plan before code.** Each milestone prompt tells Claude Code to propose a plan first. Read it. Reject anything that is not in `SPEC.md`.
- **Put standing rules in `CLAUDE.md`, not in chat.** Instructions given early in a long conversation can be lost when the context compacts. Rules in `CLAUDE.md` load every session.
- **Keep `CLAUDE.md` short.** Only what Claude Code cannot work out from the repo: rules, commands, and things it must never do.
- **Ask for tests with every function, and read the tests first.** They show what the function is meant to do in fewer lines than the code.
- **Make it prove things.** "Run it and show me the output" beats "does this work?". The `/milestone` skill enforces this at the end of each step.
- **Commit after every working step.** A dated history is your evidence that targets came before results.
- **Run `/quiz` every time.** The code only helps you if you can explain it. `DECISIONS.md` becomes your interview preparation.
- **Do not export `ANTHROPIC_API_KEY` in the shell you run Claude Code from.** If the variable is set, Claude Code can use it for its own work and bill your API key instead of your plan. Keep the key in `.env`, loaded only by the pipeline.
- **When it goes wrong twice, stop and restate.** Paste the error, say what you expected, and ask for the cause before any fix.

## 13. Defend it

You are finished when you can answer these without notes.

- Why store character offsets instead of quoting the text?
- Why does the model return a quote and not the offsets?
- Why match events at 10 km and 1 day, and how does F1 move at 5 km or 25 km?
- What does the verifier cost in recall, and is that trade worth it for an intelligence product?
- Why are there two linking rules, and what went wrong with one?
- Why collect 120 days to analyse 90?
- Where does the extractor fail on General Staff text that it handles in ISW text, and why?
- Why not fine-tune a small model on your 700 events?
- You are the only annotator. What does that do to your F1 number?
- Why is B2 run on the same model as S1?

## 14. Links

Rows marked "seen" came up live in checks on 16 November 2026. The rest are standard addresses that were not re-opened. Confirm them on first use.

| What | Link | Status |
| --- | --- | --- |
| ISW | https://understandingwar.org | Not reachable from the checking environment. Terms unverified. |
| ISW permission contact | press@understandingwar.org | Seen |
| ISW mirror, URL pattern | https://www.criticalthreats.org/analysis/russian-offensive-campaign-assessment-september-2-2026 | From the original plan |
| General Staff reports as text | https://armyinform.com.ua | Seen |
| VIINA | https://github.com/zhukovyuri/VIINA | Seen |
| ACLED | https://acleddata.com | Not re-opened |
| GeoNames dumps | https://download.geonames.org/export/dump/ | Not re-opened |
| OSM Ukraine extract | https://download.geofabrik.de/europe/ukraine.html | Not re-opened |
| Claude models and IDs | https://platform.claude.com/docs/en/models/overview | Seen |
| Claude pricing | https://platform.claude.com/docs/en/about-claude/pricing | Seen |
| Structured outputs | https://platform.claude.com/docs/en/build-with-claude/structured-outputs | Seen |
| Batch processing | https://platform.claude.com/docs/en/build-with-claude/batch-processing | Seen as a link |
| Prompt caching | https://platform.claude.com/docs/en/build-with-claude/prompt-caching | Not re-opened |
| Prompt engineering guide | https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview | Not re-opened |
| Claude Code setup | https://code.claude.com/docs/en/setup | Seen |
| Claude Code memory and CLAUDE.md | https://code.claude.com/docs/en/memory | Seen |
| Claude Code skills | https://code.claude.com/docs/en/skills | Seen |
| Claude Code settings | https://code.claude.com/docs/en/settings | Seen |
| Claude Code best practices | https://code.claude.com/docs/en/best-practices | Seen |
| GLiNER2 | https://github.com/fastino-ai/GLiNER2 | Seen |
| Original GLiNER | https://github.com/urchade/GLiNER | Seen |
| Label Studio | https://labelstud.io/guide/ | Not re-opened |
| uv | https://docs.astral.sh/uv/ | Not re-opened |
| DuckDB | https://duckdb.org/docs/ | Not re-opened |
| Pydantic | https://docs.pydantic.dev | Not re-opened |
| MapLibre GL JS | https://maplibre.org/maplibre-gl-js/docs/ | Not re-opened |
