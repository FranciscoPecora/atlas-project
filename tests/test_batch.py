from types import SimpleNamespace as NS

import pytest

from src import batch


class FakeBatches:
    """A stand-in for client.messages.batches: request ids listed in `fail` error once."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = set(fail or ())
        self.created: list[list[dict]] = []

    def create(self, requests):
        self.created.append(requests)
        return NS(id=f"b{len(self.created)}")

    def retrieve(self, batch_id):
        counts = NS(processing=0, succeeded=0, errored=0)
        return NS(processing_status="ended", request_counts=counts)

    def results(self, batch_id):
        reqs = self.created[int(batch_id[1:]) - 1]
        for r in reqs:
            cid = r["custom_id"]
            if cid in self.fail:
                self.fail.discard(cid)  # succeeds on the retry
                yield NS(custom_id=cid, result=NS(type="errored", error="overloaded"))
            else:
                msg = NS(content=[NS(type="text", text=cid)])
                yield NS(custom_id=cid, result=NS(type="succeeded", message=msg))


def client(fail=None):
    return NS(messages=NS(batches=FakeBatches(fail)))


def test_custom_id_replaces_refused_characters():
    assert batch.custom_id("S1", "2026-07-19") == "S1-2026-07-19"
    assert batch.custom_id("S3-H", "a.b", "q0001") == "S3-H-a_b-q0001"
    with pytest.raises(ValueError):
        batch.custom_id("x" * 70)


def test_submit_reuses_a_saved_batch(tmp_path):
    c = client()
    reqs = [{"custom_id": "a", "params": {}}]
    first = batch.submit(c, "job", reqs, tmp_path)
    again = batch.submit(c, "job", reqs, tmp_path)
    assert first == again == "b1"
    assert len(c.messages.batches.created) == 1  # not paid for twice


def test_submit_refuses_duplicate_ids(tmp_path):
    with pytest.raises(ValueError):
        batch.submit(client(), "dup", [{"custom_id": "a"}, {"custom_id": "a"}], tmp_path)


def test_run_retries_failed_requests_only(tmp_path):
    c = client(fail={"b"})
    reqs = [{"custom_id": x, "params": {}} for x in ("a", "b", "c")]
    ok, failed = batch.run(c, "job", reqs, poll_seconds=0, retries=2, state_dir=tmp_path)
    assert set(ok) == {"a", "b", "c"} and failed == {}
    assert [r["custom_id"] for r in c.messages.batches.created[1]] == ["b"]
    assert (tmp_path / "job-retry1.json").exists()


def test_run_with_no_requests_submits_nothing(tmp_path):
    c = client()
    assert batch.run(c, "empty", [], 0, 1, tmp_path) == ({}, {})
    assert c.messages.batches.created == []


def test_wait_polls_until_ended():
    states = iter(["in_progress", "in_progress", "ended"])
    counts = NS(processing=1, succeeded=0, errored=0)
    fake = NS(
        messages=NS(
            batches=NS(
                retrieve=lambda _id: NS(processing_status=next(states), request_counts=counts)
            )
        )
    )
    slept = []
    assert batch.wait(fake, "b1", 5, sleep=slept.append).processing_status == "ended"
    assert slept == [5, 5]


def test_reply_text_skips_thinking():
    msg = NS(
        content=[
            NS(type="thinking", thinking="x"),
            NS(type="text", text='{"a"'),
            NS(type="text", text=": 1}"),
        ]
    )
    assert batch.reply_text(msg) == '{"a": 1}'
