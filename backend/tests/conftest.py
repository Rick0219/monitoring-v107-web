import os
import tempfile
from pathlib import Path
import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="monitoring-web-tests-"))
os.environ["SECRET_KEY"] = "only-for-tests-" + "a" * 40
os.environ["FIRST_SUPERUSER_PASSWORD"] = "Testing-admin-5678!"
os.environ["FIRST_SUPERUSER"] = "admin@example.com"
os.environ["DATABASE_URL"] = "sqlite:///" + (TEST_ROOT / "test.db").as_posix()
os.environ["STORAGE_DIR"] = str(TEST_ROOT / "projects")
os.environ["AI_BASE_URL"] = ""
os.environ["AI_MODEL"] = ""

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel
from app.core.db import engine, init_db
from app.main import app

@pytest.fixture
def client():
    SQLModel.metadata.drop_all(engine)
    with Session(engine) as session:
        init_db(session)
    with TestClient(app) as client:
        yield client

def login(client, email, password="Testing-user-5678!"):
    response = client.post("/api/v1/login/access-token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}

@pytest.fixture
def accounts(client):
    admin = login(client, "admin@example.com", "Testing-admin-5678!")
    users = []
    for name in ("alice", "bob"):
        response = client.post("/api/v1/users/", headers=admin, json={"email": name+"@example.com", "password": "Testing-user-5678!", "full_name": name})
        assert response.status_code == 200, response.text
        users.append((response.json(), login(client, name+"@example.com")))
    return admin, users[0], users[1]

