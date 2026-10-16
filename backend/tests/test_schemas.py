import pytest
from app.schemas.target import TargetCreate


def test_target_creation_with_at_least_one_identifier():
    # Valid with username
    target = TargetCreate(username="johndoe")
    assert target.username == "johndoe"

    # Valid with email
    target2 = TargetCreate(email="student@university.edu.pe")
    assert target2.email == "student@university.edu.pe"

    # Valid with DNI
    target3 = TargetCreate(dni="74839201")
    assert target3.dni == "74839201"

    # Valid with full name
    target4 = TargetCreate(full_name="Juan Perez")
    assert target4.full_name == "Juan Perez"


def test_target_creation_fails_without_identifier():
    with pytest.raises(ValueError) as exc:
        TargetCreate(description="Solo una descripción sin identificador")
    assert "Debe ingresar al menos un dato identificador" in str(exc.value)


def test_investigation_read_entities_count():
    from uuid import uuid4
    from datetime import datetime, timezone
    from app.schemas.investigation import InvestigationRead

    now = datetime.now(timezone.utc)
    t_id = uuid4()
    inv_id = uuid4()

    # Default entities_count
    inv_read = InvestigationRead(
        id=inv_id,
        target_id=t_id,
        strategy="auto",
        status="completed",
        created_at=now,
    )
    assert inv_read.entities_count == 0

    # Explicit entities_count
    inv_read2 = InvestigationRead(
        id=inv_id,
        target_id=t_id,
        strategy="auto",
        status="completed",
        created_at=now,
        entities_count=42,
    )
    assert inv_read2.entities_count == 42

    # None falls back to 0
    inv_read3 = InvestigationRead(
        id=inv_id,
        target_id=t_id,
        strategy="auto",
        status="completed",
        created_at=now,
        entities_count=None,
    )
    assert inv_read3.entities_count == 0
