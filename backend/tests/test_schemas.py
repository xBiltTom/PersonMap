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
