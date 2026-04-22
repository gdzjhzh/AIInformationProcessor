from fastapi.testclient import TestClient

from collector_web.api.app import create_app
from collector_web.config import get_settings

RSS_SOURCE_URLS_JSON = """
[
  {
    "feedUrl": "http://rsshub:1200/bilibili/user/dynamic/946974?limit=1",
    "sourceName": "影视飓风",
    "sourceType": "bilibili-dynamic"
  },
  {
    "feedUrl": "http://rsshub:1200/xiaoyuzhou/podcast/648b0b641c48983391a63f98?limit=1",
    "sourceName": "42章经",
    "sourceType": "podcast"
  }
]
""".strip()


def test_home_page_shows_platform_groups(monkeypatch, tmp_path):
    db_path = tmp_path / "collector_web.sqlite"
    monkeypatch.setenv("COLLECTOR_WEB_DB_PATH", str(db_path))
    monkeypatch.setenv("RSS_SOURCE_URLS_JSON", RSS_SOURCE_URLS_JSON)
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "按平台查看订阅" in response.text
    assert "B站" in response.text
    assert "小宇宙" in response.text
    assert "影视飓风" in response.text
    assert "42章经" in response.text
    assert db_path.exists()


def test_collections_api_returns_platform_summary(monkeypatch, tmp_path):
    db_path = tmp_path / "collector_web.sqlite"
    monkeypatch.setenv("COLLECTOR_WEB_DB_PATH", str(db_path))
    monkeypatch.setenv("RSS_SOURCE_URLS_JSON", RSS_SOURCE_URLS_JSON)
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/api/collections")

    payload = response.json()
    assert response.status_code == 200
    assert payload["summary"]["collection_count"] == 1
    assert payload["summary"]["platform_count"] == 2
    assert payload["summary"]["subscription_count"] == 2
    assert payload["summary"]["active_subscription_count"] == 2
    assert payload["collections"][0]["name"] == "默认订阅合集"
    assert [group["label"] for group in payload["platform_groups"]] == ["B站", "小宇宙"]
