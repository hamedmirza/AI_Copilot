import pytest

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.api.main import app
    with TestClient(app) as c:
        yield c
