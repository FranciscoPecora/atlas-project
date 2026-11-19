#!/usr/bin/env bash
# `make all` in a fresh clone of HEAD, with a stub for the private corpus.
# The stub is the dev reports' cleaned text and the gazetteer table: what `make eval`
# reads and `make data` would otherwise rebuild over the network. Nothing else private
# is copied (no saved model runs, no ledger), so model systems are skipped by the scorer.
set -euo pipefail
repo="$(git rev-parse --show-toplevel)"
dest="${1:-$(mktemp -d)}/claimline"
git clone --quiet --no-hardlinks "$repo" "$dest"
git -C "$dest" checkout --quiet "$(git -C "$repo" rev-parse HEAD)"
mkdir -p "$dest/data/text/gsu"
for f in "$repo"/eval/gold/dev/*.jsonl; do
  day="$(basename "$f" | sed -E 's/^gsu-([0-9-]{10})__.*/\1/')"
  cp "$repo/data/text/gsu/$day.txt" "$dest/data/text/gsu/"
done
cp "$repo/data/gazetteer.parquet" "$dest/data/"
echo "fresh clone at $dest (commit $(git -C "$dest" rev-parse --short HEAD))"
echo "stub: $(ls "$dest/data/text/gsu" | tr '\n' ' ')+ gazetteer.parquet"
cd "$dest" && make all
