"""Message Batches API helpers (PLAN section 5: the full 120-day run goes through Batches).

A batch is submitted once and its id saved to data/batches/<name>.json, so a run that
stops (network, laptop lid) picks up the same batch instead of paying for a second one.
Results come back in any order and are keyed by `custom_id`, never by position.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.collect import DATA

STATE = DATA / "batches"
CUSTOM_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def custom_id(*parts: str) -> str:
    """A batch custom_id from parts; characters the API refuses become '_'."""
    cid = re.sub(r"[^a-zA-Z0-9_-]", "_", "-".join(parts))
    if not CUSTOM_ID.match(cid):
        raise ValueError(f"custom_id too long or empty: {cid!r}")
    return cid


def state_path(name: str, state_dir: Path = STATE) -> Path:
    return state_dir / f"{name}.json"


def submit(client: Any, name: str, requests: list[dict[str, Any]], state_dir: Path = STATE) -> str:
    """Create the batch `name` unless one was already submitted; return its id."""
    path = state_path(name, state_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["batch_id"]
    ids = [r["custom_id"] for r in requests]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{name}: duplicate custom_ids")
    batch = client.messages.batches.create(requests=requests)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"batch_id": batch.id, "n": len(requests)}), encoding="utf-8")
    return batch.id


def wait(
    client: Any, batch_id: str, poll_seconds: float, sleep: Callable[[float], None] = time.sleep
) -> Any:
    """Poll until the batch has ended; return the final batch object."""
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return batch
        c = batch.request_counts
        print(f"  batch {batch_id}: {c.processing} processing, {c.succeeded} done, "
              f"{c.errored} errored")  # fmt: skip
        sleep(poll_seconds)


def results(client: Any, batch_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    """({custom_id: message} for successes, {custom_id: why} for everything else)."""
    ok: dict[str, Any] = {}
    failed: dict[str, str] = {}
    for item in client.messages.batches.results(batch_id):
        r = item.result
        if r.type == "succeeded":
            ok[item.custom_id] = r.message
        else:
            failed[item.custom_id] = r.type if r.type != "errored" else f"errored: {r.error}"
    return ok, failed


def run(
    client: Any,
    name: str,
    requests: list[dict[str, Any]],
    poll_seconds: float,
    retries: int,
    state_dir: Path = STATE,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Submit, wait and collect; resubmit failed requests up to `retries` times.

    Each retry is its own saved batch (`name-retry1`, ...), so resuming is exact.
    """
    if not requests:
        return {}, {}
    by_id = {r["custom_id"]: r for r in requests}
    ok: dict[str, Any] = {}
    failed: dict[str, str] = {}
    todo = requests
    for attempt in range(retries + 1):
        label = name if attempt == 0 else f"{name}-retry{attempt}"
        batch_id = submit(client, label, todo, state_dir)
        wait(client, batch_id, poll_seconds)
        got, failed = results(client, batch_id)
        ok.update(got)
        todo = [by_id[c] for c in failed if c in by_id]
        print(f"  {label}: {len(got)} succeeded, {len(failed)} failed")
        if not todo:
            break
    return ok, failed


def reply_text(message: Any) -> str:
    """The text blocks of a reply joined (thinking blocks are skipped)."""
    return "".join(b.text for b in message.content if b.type == "text")
