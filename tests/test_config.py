import pytest

from app.core.config import PublisherConfig, Settings, load_publishers


def test_settings_defaults():
    s = Settings()
    assert s.app_env == "dev"
    assert s.window_days == 90
    assert s.request_timeout == 15.0
    assert s.max_results_per_source == 200
    assert "sqlite" in s.database_url


def test_publisher_config_id_normalized():
    pub = PublisherConfig(id="  O'Reilly  ", name="O'Reilly Media")
    assert pub.id == "o'reilly"


def test_publisher_config_id_lowercase():
    pub = PublisherConfig(id="PACKT", name="Packt Publishing")
    assert pub.id == "packt"


def test_load_publishers_missing_file():
    with pytest.raises(FileNotFoundError):
        load_publishers("/nonexistent/path/to/publishers.yml")


def test_load_publishers_window_defaults_to_settings(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "window_days", 30)
    path = tmp_path / "publishers.yml"
    path.write_text("publishers:\n  - id: pub\n    name: Pub\n")
    assert load_publishers(str(path)).window_days == 30

    path.write_text("publishers: []\nwindow_days: 45\n")
    assert load_publishers(str(path)).window_days == 45


def test_relative_paths_resolve_against_project_root():
    from app.core.config import PROJECT_ROOT

    settings = Settings(database_url="sqlite+aiosqlite:///./data/x.db", publishers_file="pubs.yml")
    assert settings.database_url == f"sqlite+aiosqlite:///{PROJECT_ROOT / 'data' / 'x.db'}"
    assert settings.publishers_file == str(PROJECT_ROOT / "pubs.yml")


def test_absolute_and_memory_database_urls_are_kept(tmp_path):
    absolute = f"sqlite+aiosqlite:///{tmp_path / 'x.db'}"
    assert Settings(database_url=absolute).database_url == absolute
    assert Settings(database_url="sqlite+aiosqlite://").database_url == "sqlite+aiosqlite://"
    assert (
        Settings(database_url="sqlite+aiosqlite:///:memory:").database_url
        == "sqlite+aiosqlite:///:memory:"
    )
    assert Settings(publishers_file=str(tmp_path / "p.yml")).publishers_file == str(
        tmp_path / "p.yml"
    )
