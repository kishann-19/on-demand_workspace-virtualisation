import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class MemoryRuntime:
    """Replace Docker for HTTP authentication and scheduling tests only."""

    def __init__(self):
        self.states = {}
        self.data = {}

    def health(self):
        return {"ready": True, "message": "Test runtime"}

    def status(self, key):
        return self.states.get(key, "missing")

    def start(self, workspace):
        self.states[workspace["id"]] = "running"
        self.data.setdefault(workspace["id"], {})

    def stop(self, key):
        self.states[key] = "stopped"

    def delete(self, key):
        self.states.pop(key, None)
        self.data.pop(key, None)

    def files(self, key, action, **kwargs):
        if action == "write":
            self.data[key][kwargs["path"]] = kwargs["content"]
            return {"saved": True}
        if action == "read":
            return {"content": self.data[key][kwargs["path"]]}
        if action == "list":
            return {"files": [{"path": p, "size": len(c)} for p, c in self.data[key].items()]}
        if action == "delete":
            del self.data[key][kwargs["path"]]
            return {"deleted": True}

    def backup(self, key):
        return json.dumps(self.data[key]).encode()

    def restore(self, key, data):
        self.data[key] = json.loads(data)


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path, admin_email="admin@example.com", admin_password="admin-test-password"
    )
    return create_app(settings, MemoryRuntime())


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def signup(client, email="student@example.com"):
    response = client.post(
        "/api/auth/register", json={"name": "Student", "email": email, "password": "test-password-123"}
    )
    assert response.status_code == 201, response.text
    client.headers["x-csrf-token"] = response.json()["csrf"]
    return response.json()["user"]


def create_workspace(client, template="python"):
    response = client.post("/api/workspaces", json={"name": "My lab", "template": template, "mode": "lab"})
    assert response.status_code == 201, response.text
    return response.json()["id"]
