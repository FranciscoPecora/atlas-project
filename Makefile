.PHONY: all lint test data data-gsu data-isw schema tasks labelstudio audit eval eval-test site

UV ?= uv
export LABEL_STUDIO_BASE_DATA_DIR := $(CURDIR)/.label-studio

all: lint test data eval site

lint:
	$(UV) run ruff check src tests eval
	$(UV) run ruff format --check src tests eval

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

eval:
	$(UV) run python -m eval.score --split dev

# Scores the TEST split once per release. Added in milestone 5.
eval-test:
	@echo "make eval-test: not built yet (milestone 5)" && exit 1

site:
	@echo "make site: arrives in milestone 6" && exit 1
