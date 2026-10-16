import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_lite_environment_rejects_a_database_other_than_personmap_lite():
    with pytest.raises(ValidationError, match="PERSONMAP_ENV=lite"):
        Settings(_env_file=None, personmap_env="lite",
            database_url="postgresql+asyncpg://postgres@localhost:5432/person_map")


def test_lite_environment_accepts_personmap_lite():
    settings = Settings(_env_file=None, personmap_env="lite",
        database_url="postgresql+asyncpg://postgres@localhost:5432/personmap_lite")
    assert settings.personmap_env == "lite"
