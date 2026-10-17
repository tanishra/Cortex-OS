import os

from cortex import config
from cortex.config import BASE_DIR, Settings, _env_files


def test_env_files_default_dev():
    files = _env_files()
    assert files[0] == BASE_DIR / ".env"
    if (BASE_DIR / ".env.dev").exists():
        assert files[-1].name == ".env.dev"


def test_env_files_profile_appended(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_PROFILE", "prod")
    assert (BASE_DIR / ".env.prod").exists()
    files = _env_files()
    assert files[-1].name == ".env.prod"


def test_env_files_missing_profile_falls_back(monkeypatch):
    monkeypatch.setattr(config, "ENV_PROFILE", "nope")
    files = _env_files()
    assert [f.name for f in files] == [".env"]


def test_profile_overrides_env(tmp_path, monkeypatch):
    """Later file wins — .env.{profile} overrides .env."""
    base = tmp_path / ".env"
    base.write_text("TASK_TIMEOUT_S=100\n")
    prof = tmp_path / ".env.custom"
    prof.write_text("TASK_TIMEOUT_S=999\n")
    monkeypatch.setattr(config, "ENV_PROFILE", "custom")

    files = _env_files()  # uses BASE_DIR — won't see tmp files; assert shape only
    assert all(str(f).startswith(str(BASE_DIR)) for f in files)

    # Direct precedence proof: pydantic settings with both files.
    s = Settings(_env_file=(base, prof))
    assert s.task_timeout_s == 999


def test_environment_reflects_profile():
    assert config.ENV_PROFILE == os.environ.get("ENV_PROFILE", "dev")
