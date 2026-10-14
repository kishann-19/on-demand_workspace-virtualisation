import logging
import threading
import time
import uuid

from fastapi import HTTPException

from .templates import TEMPLATES

logger = logging.getLogger(__name__)


class WorkspaceService:
    def __init__(self, db, runtime, storage, settings):
        self.db, self.runtime, self.storage, self.settings = db, runtime, storage, settings
        # This deployment intentionally uses one API worker. Serialize lifecycle
        # operations so quota checks and runtime changes cannot race.
        self.lock = threading.RLock()

    def event(self, user_id, workspace_id, action, detail=""):
        self.db.execute(
            "INSERT INTO events(user_id,workspace_id,action,detail,created_at) VALUES (?,?,?,?,?)",
            (user_id, workspace_id, action, detail, time.time()),
        )

    def get(self, workspace_id, user):
        workspace = self.db.one("SELECT * FROM workspaces WHERE id=?", (workspace_id,))
        if not workspace or (workspace["owner_id"] != user["id"] and user["role"] != "admin"):
            raise HTTPException(404, "Workspace not found.")
        return workspace

    def touch(self, workspace_id):
        self.db.execute("UPDATE workspaces SET last_active=? WHERE id=?", (time.time(), workspace_id))

    def reconcile(self):
        for workspace in self.db.all("SELECT * FROM workspaces WHERE status != 'error'"):
            actual = self.runtime.status(workspace["id"])
            status = "stopped" if actual == "missing" else actual
            if status != workspace["status"]:
                self.db.execute("UPDATE workspaces SET status=? WHERE id=?", (status, workspace["id"]))

    def ensure_capacity(self, owner_id):
        self.reconcile()
        running = self.db.all("SELECT owner_id FROM workspaces WHERE status='running'")
        if len(running) >= self.settings.max_host_running:
            raise HTTPException(409, "This server is at capacity. Stop a workspace and try again.")
        if sum(row["owner_id"] == owner_id for row in running) >= self.settings.max_running:
            raise HTTPException(
                409, f"You can run {self.settings.max_running} workspaces at once. Stop one first."
            )

    def create(self, user, name, template_id, mode):
        with self.lock:
            count = self.db.one("SELECT count(*) AS n FROM workspaces WHERE owner_id=?", (user["id"],))["n"]
            if count >= self.settings.max_workspaces:
                raise HTTPException(
                    409,
                    f"You can save {self.settings.max_workspaces} workspaces. Delete an unused workspace first.",
                )
            self.ensure_capacity(user["id"])
            template = TEMPLATES[template_id]
            workspace = {
                "id": uuid.uuid4().hex,
                "owner_id": user["id"],
                "name": name,
                "template": template_id,
                "mode": mode,
                "status": "running",
                "cpu": template["cpu"],
                "memory_mb": template["memory_mb"],
                "created_at": time.time(),
                "last_active": time.time(),
                "error": None,
            }
            try:
                self.runtime.start(workspace)
                for path, content in template["files"].items():
                    self.runtime.files(workspace["id"], "write", path=path, content=content)
                self.db.execute(
                    "INSERT INTO workspaces VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(workspace.values())
                )
            except Exception:
                try:
                    self.runtime.delete(workspace["id"])
                except Exception:
                    logger.exception("Could not clean up failed workspace %s", workspace["id"])
                raise
            self.event(user["id"], workspace["id"], "created", f"{mode}: {template['name']}")
            return workspace

    def start(self, workspace_id, user):
        with self.lock:
            workspace = self.get(workspace_id, user)
            if self.runtime.status(workspace_id) != "running":
                self.ensure_capacity(workspace["owner_id"])
                self.runtime.start(workspace)
                self.event(user["id"], workspace_id, "started")
            self.db.execute(
                "UPDATE workspaces SET status='running', error=NULL, last_active=? WHERE id=?",
                (time.time(), workspace_id),
            )
            return self.get(workspace_id, user)

    def stop(self, workspace_id, user, automatic=False):
        with self.lock:
            self.get(workspace_id, user)
            self.runtime.stop(workspace_id)
            self.db.execute("UPDATE workspaces SET status='stopped' WHERE id=?", (workspace_id,))
            self.event(user["id"], workspace_id, "idle_shutdown" if automatic else "stopped")
            return self.get(workspace_id, user)

    def delete(self, workspace_id, user):
        with self.lock:
            self.get(workspace_id, user)
            # Delete external artifacts before metadata, so a failure is retryable.
            for backup in self.db.all("SELECT * FROM backups WHERE workspace_id=?", (workspace_id,)):
                self.storage.delete(backup)
                self.db.execute("DELETE FROM backups WHERE id=?", (backup["id"],))
            self.runtime.delete(workspace_id)
            self.db.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))
            self.event(user["id"], workspace_id, "deleted")

    def require_running(self, workspace_id, user):
        workspace = self.get(workspace_id, user)
        if self.runtime.status(workspace_id) != "running":
            raise HTTPException(409, "Start this workspace to open the editor and terminal.")
        return workspace

    def require_stopped(self, workspace_id, user):
        workspace = self.get(workspace_id, user)
        if self.runtime.status(workspace_id) == "running":
            raise HTTPException(409, "Stop this workspace before backing up or restoring its files.")
        return workspace

    def backup(self, workspace_id, user):
        with self.lock:
            self.require_stopped(workspace_id, user)
            if (
                self.db.one("SELECT count(*) AS n FROM backups WHERE workspace_id=?", (workspace_id,))["n"]
                >= 10
            ):
                raise HTTPException(409, "A workspace can keep 10 backups. Delete an older backup first.")
            data = self.runtime.backup(workspace_id)
            backup_id = uuid.uuid4().hex
            key = f"cloudlab/{user['id']}/{workspace_id}/{backup_id}.tar.gz"
            storage = self.storage.put(key, data)
            self.db.execute(
                "INSERT INTO backups VALUES (?,?,?,?,?,?)",
                (backup_id, workspace_id, time.time(), len(data), storage, key),
            )
            self.event(user["id"], workspace_id, "backup_created", storage)
            return self.db.one("SELECT * FROM backups WHERE id=?", (backup_id,))

    def restore(self, workspace_id, backup_id, user):
        with self.lock:
            self.require_stopped(workspace_id, user)
            backup = self.get_backup(workspace_id, backup_id, user)
            # Save current data in memory for rollback if extraction fails.
            previous = self.runtime.backup(workspace_id)
            try:
                self.runtime.restore(workspace_id, self.storage.get(backup))
            except Exception:
                self.runtime.restore(workspace_id, previous)
                raise
            self.event(user["id"], workspace_id, "backup_restored", backup_id)

    def get_backup(self, workspace_id, backup_id, user):
        self.get(workspace_id, user)
        backup = self.db.one("SELECT * FROM backups WHERE id=? AND workspace_id=?", (backup_id, workspace_id))
        if not backup:
            raise HTTPException(404, "Backup not found.")
        return backup

    def cleanup_idle(self):
        with self.lock:
            self.reconcile()
            threshold = time.time() - self.settings.idle_minutes * 60
            for workspace in self.db.all(
                "SELECT * FROM workspaces WHERE status='running' AND last_active<?", (threshold,)
            ):
                try:
                    self.stop(
                        workspace["id"], {"id": workspace["owner_id"], "role": "student"}, automatic=True
                    )
                except Exception:
                    logger.exception("Idle shutdown failed for %s", workspace["id"])
