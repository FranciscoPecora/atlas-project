#!/usr/bin/env bash
# `make all` in a fresh clone of HEAD, with a stub for the private corpus.
# The stub is the dev reports' cleaned text and the gazetteer table: what `make eval`
# reads and `make data` would otherwise rebuild over the network. Nothing else private
# is copied (no saved model runs, no ledger), so model systems are skipped by the scorer.
set -euo pipefail
repo="$(git rev-parse --show-toplevel)"
dest="${1:-$(mktemp -d)}/atlas"
git clone --quiet --no-hardlinks "$repo" "$dest"
git -C "$dest" checkout --quiet "$(git -C "$repo" rev-parse HEAD)"
for f in "$repo"/eval/gold/dev/*.jsonl; do
  # <source>-<YYYY-MM-DD>__<sector>__pass<n>.jsonl, for gsu, af and rumod
  name="$(basename "$f")"
  source="${name%%-*}"
  day="$(echo "$name" | sed -E 's/^[a-z]+-([0-9]{4}-[0-9]{2}-[0-9]{2})__.*/\1/')"
  mkdir -p "$dest/data/text/$source"
  cp "$repo/data/text/$source/$day.txt" "$dest/data/text/$source/"
done
cp "$repo/data/gazetteer.parquet" "$dest/data/"
echo "fresh clone at $dest (commit $(git -C "$dest" rev-parse --short HEAD))"
echo "stub: $(cd "$dest/data/text" && ls */*.txt | tr "\n" " ")+ gazetteer.parquet"
cd "$dest" && make all
