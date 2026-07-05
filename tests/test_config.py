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
