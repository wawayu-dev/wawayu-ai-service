from fastapi.testclient import TestClient

from app.main import create_app


def test_demo_page_and_assets_are_served() -> None:
    client = TestClient(create_app())

    page = client.get("/demo/")
    stylesheet = client.get("/demo/styles.css")
    script = client.get("/demo/app.js")

    assert page.status_code == 200
    assert "填充测试数据" in page.text
    assert "AI 招聘事件跟进" in page.text
    assert stylesheet.status_code == 200
    assert "--brand" in stylesheet.text
    assert script.status_code == 200
    assert "/v1/capabilities/recruitment-event-follow-up/analyze" in script.text


def test_demo_path_redirects_to_trailing_slash() -> None:
    client = TestClient(create_app(), follow_redirects=False)

    response = client.get("/demo")

    assert response.status_code == 307
    assert response.headers["location"].endswith("/demo/")
