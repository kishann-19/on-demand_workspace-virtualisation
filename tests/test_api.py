import time
from concurrent.futures import ThreadPoolExecutor

from conftest import create_workspace, signup
from fastapi import HTTPException


def test_authentication_csrf_logout_and_password_storage(client, app):
    assert client.get("/api/workspaces").status_code == 401
    user = signup(client)
    stored = app.state.db.one("SELECT password FROM users WHERE id=?", (user["id"],))["password"]
    assert stored.startswith("scrypt$") and "test-password" not in stored
    assert (
        "HttpOnly"
        in client.post(
            "/api/auth/login", json={"email": "student@example.com", "password": "test-password-123"}
        ).headers["set-cookie"]
    )
    # Signing in rotates the CSRF token; the previous one no longer works.
    assert client.post("/api/workspaces", json={"name": "Test", "template": "python"}).status_code == 403
    client.headers["x-csrf-token"] = client.get("/api/auth/me").json()["csrf"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_cross_user_access_and_admin_permissions(client, app):
    signup(client)
    key = create_workspace(client)
    client.post("/api/auth/logout")
    signup(client, "other@example.com")
    for suffix in ("", "/files", "/backups", "/file?path=main.py", "/metrics", "/preview"):
        assert client.get(f"/api/workspaces/{key}{suffix}").status_code == 404
    for action in ("start", "stop", "backups"):
        assert client.post(f"/api/workspaces/{key}/{action}").status_code == 404
    assert client.delete(f"/api/workspaces/{key}").status_code == 404
    assert client.get("/api/admin/overview").status_code == 403
    admin = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin-test-password"}
    )
    client.headers["x-csrf-token"] = admin.json()["csrf"]
    assert len(client.get("/api/admin/overview").json()["users"]) == 3
    assert client.post(f"/api/workspaces/{key}/stop").status_code == 200


def test_idle_shutdown_keeps_files_and_reads_do_not_reset_timer(client, app):
    signup(client)
    key = create_workspace(client)
    db = app.state.db
    db.execute("UPDATE workspaces SET last_active=? WHERE id=?", (time.time() - 3600, key))
    client.get(f"/api/workspaces/{key}/files")
    app.state.service.cleanup_idle()
    assert client.get(f"/api/workspaces/{key}").json()["status"] == "stopped"
    client.post(f"/api/workspaces/{key}/start")
    assert "scores" in client.get(f"/api/workspaces/{key}/file", params={"path": "main.py"}).json()["content"]
    assert db.one("SELECT action FROM events ORDER BY id DESC LIMIT 1")["action"] == "started"


def test_quota_atomic_under_concurrent_requests(client, app):
    user = signup(client)
    service = app.state.service

    def create(_):
        try:
            return service.create(user, "Concurrent", "python", "lab")["id"]
        except HTTPException as exc:
            assert exc.status_code == 409
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(create, range(6)))
    assert sum(value is not None for value in results) == 2


def test_backup_requires_stop_and_restores_files(client):
    signup(client)
    key = create_workspace(client)
    assert client.post(f"/api/workspaces/{key}/backups").status_code == 409
    client.post(f"/api/workspaces/{key}/stop")
    backup = client.post(f"/api/workspaces/{key}/backups").json()
    client.post(f"/api/workspaces/{key}/start")
    client.put(f"/api/workspaces/{key}/file", json={"path": "main.py", "content": "changed"})
    client.post(f"/api/workspaces/{key}/stop")
    assert client.post(f"/api/workspaces/{key}/backups/{backup['id']}/restore").status_code == 200
    client.post(f"/api/workspaces/{key}/start")
    assert "scores" in client.get(f"/api/workspaces/{key}/file?path=main.py").json()["content"]
    assert client.get(f"/api/workspaces/{key}/backups/{backup['id']}/download").status_code == 200
    assert client.delete(f"/api/workspaces/{key}/backups/{backup['id']}").status_code == 200
    assert client.get(f"/api/workspaces/{key}/backups").json() == []


def test_validation_origin_and_login_throttle(client):
    payload = {"name": "Test", "email": "student@example.com", "password": "too-short"}
    assert client.post("/api/auth/register", json=payload).status_code == 422
    assert (
        client.post(
            "/api/auth/register", json=payload, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"email": "missing@example.com", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post("/api/auth/login", json={"email": "missing@example.com", "password": "wrong"}).status_code
        == 429
    )
    signup(client)
    assert (
        client.post("/api/workspaces", json={"name": "Test", "template": "arbitrary-image"}).status_code
        == 422
    )
    assert client.post("/api/workspaces", json={"name": "   ", "template": "python"}).status_code == 422


def test_preview_is_sandboxed_and_contains_local_assets(client):
    signup(client)
    key = create_workspace(client, "web")
    response = client.get(f"/api/workspaces/{key}/preview")
    assert response.status_code == 200
    assert "addEventListener" in response.text and "#18392e" in response.text
    assert "sandbox allow-scripts" in response.headers["content-security-policy"]
    assert "allow-same-origin" not in response.headers["content-security-policy"]
    assert "x-frame-options" not in response.headers


def test_stopped_quota_and_failed_create_rollback(client, app):
    signup(client)
    for _ in range(5):
        key = create_workspace(client)
        client.post(f"/api/workspaces/{key}/stop")
    assert client.post("/api/workspaces", json={"name": "Too many", "template": "linux"}).status_code == 409
    client.delete(f"/api/workspaces/{key}")
    create_workspace(client)
