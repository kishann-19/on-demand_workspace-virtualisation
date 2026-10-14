import os
import time
import uuid

import pytest
from conftest import create_workspace, signup
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime import DockerRuntime

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("RUN_DOCKER_TESTS") != "1", reason="Set RUN_DOCKER_TESTS=1 to test real containers"
    ),
]


@pytest.fixture
def docker_client(tmp_path):
    settings = Settings(data_dir=tmp_path)
    runtime = DockerRuntime(settings)
    assert runtime.health()["ready"], "Build the workspace image before running Docker integration tests."
    app = create_app(settings, runtime)
    with TestClient(app) as client:
        signup(client, f"docker-{uuid.uuid4().hex}@example.com")
        try:
            yield client, runtime, app
        finally:
            for row in app.state.db.all("SELECT id FROM workspaces"):
                runtime.delete(row["id"])


@pytest.mark.parametrize(
    "template,command,expected",
    [
        ("linux", ["bash", "hello.sh"], "Linux lab"),
        ("python", ["python", "main.py"], "Class average: 91.0"),
        ("web", ["node", "main.js"], "isolated Node.js"),
    ],
)
def test_real_runtime_resources_persistence_backups(docker_client, template, command, expected):
    client, runtime, app = docker_client
    key = create_workspace(client, template)
    container = runtime.container(key)
    result = container.exec_run(command)
    assert result.exit_code == 0 and expected in result.output.decode()
    config = container.attrs["HostConfig"]
    assert config["ReadonlyRootfs"] and config["NetworkMode"] == "none"
    assert config["PidsLimit"] == 128 and config["Memory"] > 0 and config["NanoCpus"] > 0
    assert container.attrs["Config"]["User"] == "1000:1000"
    assert (
        client.put(
            f"/api/workspaces/{key}/file", json={"path": "saved.txt", "content": "keep this"}
        ).status_code
        == 200
    )
    assert client.get(f"/api/workspaces/{key}/file", params={"path": "../etc/passwd"}).status_code == 422
    client.post(f"/api/workspaces/{key}/stop")
    backup = client.post(f"/api/workspaces/{key}/backups")
    assert backup.status_code == 201, backup.text
    client.post(f"/api/workspaces/{key}/start")
    assert client.get(f"/api/workspaces/{key}/file?path=saved.txt").json()["content"] == "keep this"
    client.put(f"/api/workspaces/{key}/file", json={"path": "saved.txt", "content": "changed"})
    client.post(f"/api/workspaces/{key}/stop")
    response = client.post(f"/api/workspaces/{key}/backups/{backup.json()['id']}/restore")
    assert response.status_code == 200, response.text
    client.post(f"/api/workspaces/{key}/start")
    assert client.get(f"/api/workspaces/{key}/file?path=saved.txt").json()["content"] == "keep this"
    assert client.get(f"/api/workspaces/{key}/metrics").status_code == 200
    # Recreating a missing container preserves its named volume too.
    runtime.container(key).remove(force=True)
    assert client.post(f"/api/workspaces/{key}/start").status_code == 200
    assert client.get(f"/api/workspaces/{key}/file?path=saved.txt").json()["content"] == "keep this"
    assert client.delete(f"/api/workspaces/{key}").status_code == 200
    assert runtime.status(key) == "missing"


def test_real_browser_terminal(docker_client):
    client, runtime, app = docker_client
    key = create_workspace(client)
    with client.websocket_connect(
        f"/api/workspaces/{key}/terminal", headers={"Origin": "http://localhost:8000"}
    ) as socket:
        socket.send_json({"csrf": client.headers["x-csrf-token"]})
        socket.send_json({"type": "resize", "cols": 100, "rows": 25})
        socket.send_json({"type": "input", "data": "python -c 'print(21*2)'\r"})
        output = b""
        deadline = time.time() + 10
        while b"42" not in output and time.time() < deadline:
            output += socket.receive_bytes()
        assert b"42" in output
        socket.send_json({"type": "input", "data": "exit\r"})
