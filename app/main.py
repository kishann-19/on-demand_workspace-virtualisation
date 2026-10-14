import asyncio
import contextlib
import json
import logging
import socket
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from docker.errors import DockerException
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .auth import (
    COOKIE,
    admin_user,
    authenticate,
    create_user,
    current_user,
    public_user,
    set_session,
    token_hash,
    verify_password,
)
from .config import Settings
from .db import Database
from .preview import build_preview
from .runtime import DockerRuntime, RuntimeError
from .service import WorkspaceService
from .storage import BackupStorage
from .templates import list_templates

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.split("@")[1] or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address.")
        return value


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("Enter your name.")
        return value.strip()


class NewWorkspace(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w .()-]+$")
    template: Literal["linux", "python", "web"]
    mode: Literal["lab", "workspace"] = "lab"

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("Enter a workspace name.")
        return value.strip()


class FileWrite(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=65536)


def create_app(settings=None, runtime=None):
    settings = settings or Settings()
    db = Database(settings.data_dir / "cloudlab.db")
    runtime = runtime or DockerRuntime(settings)
    storage = BackupStorage(settings)
    service = WorkspaceService(db, runtime, storage, settings)

    async def sweeper():
        while True:
            try:
                await run_in_threadpool(service.cleanup_idle)
            except Exception:
                logger.exception("Could not reconcile Docker workspace state")
            await asyncio.sleep(30)

    @asynccontextmanager
    async def lifespan(app):
        if settings.admin_email and settings.admin_password:
            credentials = Registration(
                name="Administrator", email=settings.admin_email, password=settings.admin_password
            )
            if not db.one("SELECT id FROM users WHERE email=?", (credentials.email,)):
                create_user(db, credentials.name, credentials.email, credentials.password, "admin")
        task = asyncio.create_task(sweeper())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="CloudLab API", version="1.0.0", lifespan=lifespan)
    app.state.db, app.state.service = db, service

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != settings.origin:
                return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 300_000:
                return JSONResponse({"detail": "Request body is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.endswith("/preview"):
            response.headers["Content-Security-Policy"] = (
                "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
            )
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DockerException)
    async def docker_error(request, exc):
        logger.error("Docker operation failed: %s", exc)
        return JSONResponse(
            {
                "detail": "Docker operation failed. Check that Docker is running and the workspace image is built."
            },
            status_code=503,
        )

    @app.exception_handler(RuntimeError)
    async def workspace_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {"registration": settings.registration}

    def check_auth_limit(request, email):
        key = f"{request.client.host if request.client else 'unknown'}:{email}"
        with service.lock:
            db.execute("DELETE FROM login_attempts WHERE created_at<?", (time.time() - 900,))
            if db.one("SELECT count(*) AS n FROM login_attempts WHERE key=?", (key,))["n"] >= 10:
                raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
            db.execute("INSERT INTO login_attempts VALUES (?,?)", (key, time.time()))
        return key

    @app.post("/api/auth/register", status_code=201)
    def register(body: Registration, request: Request, response: Response):
        if not settings.registration:
            raise HTTPException(403, "Registration is disabled. Contact your administrator.")
        check_auth_limit(request, body.email)
        try:
            user = create_user(db, body.name, body.email, body.password)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "An account already uses this email address.") from None
        service.event(user["id"], None, "registered")
        return set_session(db, response, user, settings)

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        key = check_auth_limit(request, body.email)
        user = db.one("SELECT * FROM users WHERE email=?", (body.email,))
        if not user or not verify_password(body.password, user["password"]):
            raise HTTPException(401, "Email or password is incorrect.")
        db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
        return set_session(db, response, user, settings)

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return {"user": public_user(user), "csrf": user["csrf"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(request.cookies[COOKIE]),))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/templates")
    def templates(user=Depends(current_user)):
        return list_templates()

    @app.get("/api/system")
    def system(user=Depends(current_user)):
        return {
            "runtime": runtime.health(),
            "backup_storage": "s3" if settings.backup_bucket else "local",
            "idle_minutes": settings.idle_minutes,
            "max_workspaces": settings.max_workspaces,
            "max_running": settings.max_running,
            "max_host_running": settings.max_host_running,
        }

    @app.get("/api/workspaces")
    def workspaces(user=Depends(current_user)):
        with service.lock:
            service.reconcile()
            return db.all("SELECT * FROM workspaces WHERE owner_id=? ORDER BY created_at DESC", (user["id"],))

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(body: NewWorkspace, user=Depends(current_user)):
        return service.create(user, body.name, body.template, body.mode)

    @app.get("/api/workspaces/{workspace_id}")
    def workspace(workspace_id: str, user=Depends(current_user)):
        return service.get(workspace_id, user)

    @app.post("/api/workspaces/{workspace_id}/start")
    def start(workspace_id: str, user=Depends(current_user)):
        return service.start(workspace_id, user)

    @app.post("/api/workspaces/{workspace_id}/stop")
    def stop(workspace_id: str, user=Depends(current_user)):
        return service.stop(workspace_id, user)

    @app.delete("/api/workspaces/{workspace_id}")
    def delete(workspace_id: str, user=Depends(current_user)):
        service.delete(workspace_id, user)
        return {"deleted": True}

    @app.get("/api/workspaces/{workspace_id}/files")
    def files(workspace_id: str, user=Depends(current_user)):
        with service.lock:
            service.require_running(workspace_id, user)
            return runtime.files(workspace_id, "list")

    @app.get("/api/workspaces/{workspace_id}/file")
    def read_file(workspace_id: str, path: str, user=Depends(current_user)):
        with service.lock:
            service.require_running(workspace_id, user)
            return runtime.files(workspace_id, "read", path=path)

    @app.put("/api/workspaces/{workspace_id}/file")
    def write_file(workspace_id: str, body: FileWrite, user=Depends(current_user)):
        with service.lock:
            service.require_running(workspace_id, user)
            result = runtime.files(workspace_id, "write", path=body.path, content=body.content)
            service.touch(workspace_id)
            return result

    @app.delete("/api/workspaces/{workspace_id}/file")
    def delete_file(workspace_id: str, path: str, user=Depends(current_user)):
        with service.lock:
            service.require_running(workspace_id, user)
            result = runtime.files(workspace_id, "delete", path=path)
            service.touch(workspace_id)
            return result

    @app.get("/api/workspaces/{workspace_id}/metrics")
    def metrics(workspace_id: str, user=Depends(current_user)):
        service.require_running(workspace_id, user)
        return runtime.metrics(workspace_id)

    @app.get("/api/workspaces/{workspace_id}/preview")
    def preview(workspace_id: str, user=Depends(current_user)):
        with service.lock:
            service.require_running(workspace_id, user)
            html = build_preview(lambda path: runtime.files(workspace_id, "read", path=path)["content"])
            return Response(html, media_type="text/html")

    @app.get("/api/workspaces/{workspace_id}/backups")
    def backups(workspace_id: str, user=Depends(current_user)):
        service.get(workspace_id, user)
        return db.all("SELECT * FROM backups WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,))

    @app.post("/api/workspaces/{workspace_id}/backups", status_code=201)
    def backup(workspace_id: str, user=Depends(current_user)):
        return service.backup(workspace_id, user)

    @app.post("/api/workspaces/{workspace_id}/backups/{backup_id}/restore")
    def restore(workspace_id: str, backup_id: str, user=Depends(current_user)):
        service.restore(workspace_id, backup_id, user)
        return {"restored": True}

    @app.get("/api/workspaces/{workspace_id}/backups/{backup_id}/download")
    def download(workspace_id: str, backup_id: str, user=Depends(current_user)):
        backup = service.get_backup(workspace_id, backup_id, user)
        return Response(
            storage.get(backup),
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="cloudlab-{backup_id}.tar.gz"'},
        )

    @app.delete("/api/workspaces/{workspace_id}/backups/{backup_id}")
    def delete_backup(workspace_id: str, backup_id: str, user=Depends(current_user)):
        with service.lock:
            backup = service.get_backup(workspace_id, backup_id, user)
            storage.delete(backup)
            db.execute("DELETE FROM backups WHERE id=?", (backup_id,))
            service.event(user["id"], workspace_id, "backup_deleted", backup_id)
        return {"deleted": True}

    @app.get("/api/admin/overview")
    def admin(user=Depends(admin_user)):
        with service.lock:
            service.reconcile()
            return {
                "users": db.all("SELECT id,name,email,role,created_at FROM users ORDER BY created_at DESC"),
                "workspaces": db.all(
                    "SELECT w.*,u.email AS owner_email FROM workspaces w JOIN users u ON w.owner_id=u.id ORDER BY w.created_at DESC"
                ),
                "events": db.all(
                    "SELECT e.*,u.email FROM events e LEFT JOIN users u ON e.user_id=u.id ORDER BY e.id DESC LIMIT 100"
                ),
            }

    @app.websocket("/api/workspaces/{workspace_id}/terminal")
    async def terminal(websocket: WebSocket, workspace_id: str):
        user = authenticate(db, websocket.cookies.get(COOKIE))
        if not user or websocket.headers.get("origin") != settings.origin:
            await websocket.close(code=1008)
            return
        try:
            await run_in_threadpool(service.require_running, workspace_id, user)
        except (HTTPException, DockerException):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        attached = None
        tasks = []
        try:
            # Authenticate the socket with a CSRF token in its first message;
            # never put session credentials in a URL or access log.
            hello = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            import hmac

            if not isinstance(hello, dict) or not hmac.compare_digest(
                str(hello.get("csrf", "")), user["csrf"]
            ):
                await websocket.close(code=1008)
                return
            execution_id, attached = await run_in_threadpool(runtime.terminal, workspace_id)
            sock = attached._sock
            sock.settimeout(1)

            async def receive():
                while True:
                    message = await websocket.receive_text()
                    if len(message) > 16384 or not authenticate(db, websocket.cookies.get(COOKIE)):
                        await websocket.close(code=1008)
                        return
                    payload = json.loads(message)
                    if payload.get("type") == "input":
                        data = str(payload.get("data", "")).encode()
                        await run_in_threadpool(sock.sendall, data)
                        await run_in_threadpool(service.touch, workspace_id)
                    elif payload.get("type") == "resize":
                        await run_in_threadpool(
                            runtime.resize,
                            execution_id,
                            max(20, min(int(payload["cols"]), 300)),
                            max(5, min(int(payload["rows"]), 100)),
                        )

            async def send():
                while True:
                    if not authenticate(db, websocket.cookies.get(COOKIE)):
                        await websocket.close(code=1008)
                        return
                    try:
                        data = await run_in_threadpool(sock.recv, 8192)
                    except socket.timeout:
                        continue
                    if not data:
                        return
                    await websocket.send_bytes(data)

            tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, OSError, ValueError, asyncio.TimeoutError, DockerException):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if attached:
                attached.close()
            with contextlib.suppress(Exception):
                await websocket.close()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app
