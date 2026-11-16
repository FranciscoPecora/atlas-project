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
