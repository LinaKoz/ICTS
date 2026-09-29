"""Israeli ID checksum (§8 T5): valid and invalid cases."""
from __future__ import annotations

import pytest

from app.workers.national_id import israeli_id_checksum_ok, national_id_error


@pytest.mark.parametrize("nid", ["111111118", "222222226", "333333334", "444444442", "555555556", "012345674", "000000018"])
def test_valid_ids(nid):
    assert national_id_error(nid) is None


@pytest.mark.parametrize("nid", ["111111111", "123456789", "012345678", "000000019"])
def test_bad_checksum(nid):
    assert not israeli_id_checksum_ok(nid)
    assert "checksum" in national_id_error(nid)


def test_length_and_format_errors():
    assert "exactly 9 digits (got 8)" in national_id_error("12345674")  # dropped leading zero is never padded
    assert "leading zeros" in national_id_error("12345674")
    assert "exactly 9 digits" in national_id_error("1234567890")
    assert "exactly 9 digits" in national_id_error("1.23E+08")
    assert "exactly 9 digits" in national_id_error("12345 674")
    assert "exactly 9 digits" in national_id_error("")
    assert "exactly 9 digits" in national_id_error("١٢٣٤٥٦٧٨٩")  # non-ASCII digits are not digits here


def test_seed_workers_have_valid_ids():
    from app.seed import _SAMPLE_WORKERS

    assert [nid for nid, _, _ in _SAMPLE_WORKERS if national_id_error(nid)] == []
