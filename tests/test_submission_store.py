"""Tests for SubmissionStore."""
from benchmark_platform.web.submission_store import SubmissionRecord, SubmissionStore


def test_add_and_query():
    store = SubmissionStore()
    r1 = SubmissionRecord(
        timestamp="2026-05-10T14:00:00Z",
        challenge_code="c1",
        benchmark_id="XBEN-001-24",
        challenge_name="Test Challenge",
        flag_id="default",
        flag_value="flag{test}",
        correct=True,
        points=200,
    )
    r2 = SubmissionRecord(
        timestamp="2026-05-10T14:01:00Z",
        challenge_code="c2",
        benchmark_id="XBEN-002-24",
        challenge_name="Another",
        flag_id="default",
        flag_value="flag{wrong}",
        correct=False,
        points=0,
    )
    store.add(r1)
    store.add(r2)
    all_records = store.query()
    assert len(all_records) == 2
    assert all_records[0].timestamp == "2026-05-10T14:01:00Z"  # newest first


def test_query_filter_correct():
    store = SubmissionStore()
    store.add(SubmissionRecord("t1", "c1", "B1", "N1", "d", "f", True, 200))
    store.add(SubmissionRecord("t2", "c2", "B2", "N2", "d", "f", False, 0))
    store.add(SubmissionRecord("t3", "c3", "B3", "N3", "d", "f", True, 300))
    correct_only = store.query(correct=True)
    assert len(correct_only) == 2
    assert all(r.correct for r in correct_only)


def test_query_limit_offset():
    store = SubmissionStore()
    for i in range(20):
        store.add(SubmissionRecord(f"t{i}", f"c{i}", f"B{i}", f"N{i}", "d", "f", True, 100))
    page = store.query(limit=5, offset=5)
    assert len(page) == 5
    assert page[0].timestamp == "t14"  # newest first, skip 5


def test_total_counts():
    store = SubmissionStore()
    store.add(SubmissionRecord("t1", "c1", "B1", "N1", "d", "f", True, 200))
    store.add(SubmissionRecord("t2", "c2", "B2", "N2", "d", "f", False, 0))
    store.add(SubmissionRecord("t3", "c3", "B3", "N3", "d", "f", True, 300))
    assert store.total_count == 3
    assert store.correct_count == 2
    assert store.incorrect_count == 1


def test_jsonl_persistence(tmp_path):
    log_path = tmp_path / "submissions.jsonl"
    store = SubmissionStore(log_path=log_path)
    store.add(SubmissionRecord("t1", "c1", "B1", "N1", "d", "f", True, 200))
    assert log_path.exists()
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    assert '"correct": true' in lines[0]
