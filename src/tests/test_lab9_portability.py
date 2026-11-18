"""A Windows build must produce the same eval-set bytes as the Linux CI checkout."""
import hashlib
import json

import pytest

from lab9 import evalset

pytestmark = pytest.mark.student


def test_lab9_generated_eval_set_keeps_lf_for_git_and_ci(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "claims.jsonl"
    source.write_text(json.dumps({"claim_id": "C-001", "matrix_id": "T01", "expected": {"refund_vnd": 0}}),
                      encoding="utf-8")
    evalset.build(source)
    content = evalset.ITEMS.read_bytes()
    assert b"\r\n" not in content
    assert evalset.sha12(evalset.ITEMS) == hashlib.sha256(content).hexdigest()[:12]
