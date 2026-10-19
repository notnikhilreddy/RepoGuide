from fastapi.testclient import TestClient

from repoguide.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_question():
    response = client.post(
        "/repositories/example/ask",
        json={
            "question": "Hi",
            "top_k": 8,
        },
    )

    assert response.status_code == 422


def test_invalid_top_k():
    response = client.post(
        "/repositories/example/ask",
        json={
            "question": "Where is authentication handled?",
            "top_k": 100,
        },
    )

    assert response.status_code == 422