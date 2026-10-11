"""Cursor and compaction checks without database/network access."""
import uuid

import pytest
from fastapi import HTTPException

from app.services.workspace_updates import decode_cursor, encode_cursor


def test_cursor_roundtrip_is_bound_to_dossier():
    case = uuid.uuid4()
    cursor = encode_cursor(case, 12, 3)
    assert decode_cursor(cursor, case) == (12, 3)
    with pytest.raises(HTTPException) as exc:
        decode_cursor(cursor, uuid.uuid4())
    assert exc.value.status_code == 422


@pytest.mark.parametrize("cursor", ["invalid", "?", "W10=", "x" * 257])
def test_malformed_cursors_are_rejected(cursor):
    with pytest.raises(HTTPException) as exc:
        decode_cursor(cursor, uuid.uuid4())
    assert exc.value.status_code == 422
