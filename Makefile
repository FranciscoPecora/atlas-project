.PHONY: all lint test data data-gsu data-isw schema tasks labelstudio audit handlabel mark-fields mark-places eval eval-test ledger link analysis release site pages fresh-clone

UV ?= uv
export LABEL_STUDIO_BASE_DATA_DIR := $(CURDIR)/.label-studio

# End to end on what a clone has: lint, tests, dev scores, site. Collecting the corpus
# (make data) is slow and uses the network, so it is not part of `all`; `make eval`
# needs the dev reports in data/text/ and data/gazetteer.parquet (see README).
all: lint test eval site

lint:
	$(UV) run ruff check src tests eval notebooks
	$(UV) run ruff format --check src tests eval notebooks

test:
	$(UV) run pytest -q

# Collect and clean the corpus (slow, network). ISW stays off until permission.
data: data-gsu

data-gsu:
	$(UV) run python -m src.collect --source gsu

data-isw:
	$(UV) run python -m src.collect --source isw

schema:
	$(UV) run python -m src.schema

# Label Studio import file for the gold units that are collected so far.
tasks:
	$(UV) run python -m src.labels tasks

labelstudio:
	label-studio start --port 8080 --internal-host 127.0.0.1

# Build and open the spot-check page for the machine-made GSU dev key.
audit:
	$(UV) run python -m src.audit build
	open data/audit/audit.html

# Build and open the hand-labelling page for the GSU dev reports (English, no pre-fills).
handlabel:
	$(UV) run python -m src.handlabel build
	open data/handlabel/label.html

# Milestone 4 hand checks: build and open the marking pages (local, hold report text).
mark-fields:
	$(UV) run python -m src.audit_fields page
	open data/audit/fields_check.html

mark-places:
	$(UV) run python -m src.geocode_check page
	open data/audit/places_check.html

eval:
	$(UV) run python -m eval.score --split dev

# Scores the TEST split once per release (eval/run_test_split.py). Refuses if
# eval/test_run.json exists, on uncommitted changes, or if a saved run is missing.
eval-test:
	$(UV) run python -m eval.run_test_split

# Full-corpus run through the Message Batches API, then data/ledger.parquet (paid, slow).
ledger:
	$(UV) run python -m src.ledger run

# Rules 7a and 7b over the ledger (no API).
link:
	$(UV) run python -m src.link

# H2 and the VIINA correlation (rows appended to eval/results.csv), then both notebooks.
analysis:
	$(UV) run python -m src.h2
	$(UV) run python -m src.viina
	PYTHONPATH=. $(UV) run python notebooks/01_claimed_vs_confirmed.py
	PYTHONPATH=. $(UV) run python notebooks/02_viina.py

# Public ledger without source text (release/), from the private ledger and link tables.
release:
	$(UV) run python -m src.release

# Map data for the static demo, from the committed release (48-hour delay applied).
site:
	$(UV) run python -m src.site_build

# Publish site/ as committed at HEAD to the gh-pages branch that GitHub Pages serves.
# Run after `make site` and a commit. Pages: Settings -> Pages -> Deploy from a branch,
# gh-pages, / (root).
pages:
	@git diff --quiet HEAD -- site || (echo "commit site/ first" && exit 1)
	git push origin "$$(git subtree split --prefix site HEAD)":refs/heads/gh-pages

# Run `make all` in a fresh clone of HEAD with only the dev reports and the gazetteer
# copied in as the private stub. Needs a clean, committed tree.
fresh-clone:
	bash scripts/fresh_clone.sh
