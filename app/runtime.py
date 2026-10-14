import base64
import json
import socket

import docker
from docker.errors import NotFound


class RuntimeError(Exception):
    pass


class DockerRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.client = docker.DockerClient(base_url=settings.docker_url, timeout=35, version="1.43")

    def health(self):
        try:
            self.client.ping()
            self.client.images.get(self.settings.runtime_image)
            return {"ready": True, "message": "Docker and workspace image are ready."}
        except Exception:
            return {
                "ready": False,
                "message": "Docker or the workspace image is unavailable. Run the setup steps in the README.",
            }

    @staticmethod
    def name(workspace_id):
        return f"cloudlab-{workspace_id}"

    def container(self, workspace_id):
        return self.client.containers.get(self.name(workspace_id))

    def status(self, workspace_id):
        try:
            container = self.container(workspace_id)
            return "running" if container.status == "running" else "stopped"
        except NotFound:
            return "missing"

    def create(self, workspace):
        # Named volumes are populated from the image's uid-1000 /workspace.
        return self.client.containers.create(
            self.settings.runtime_image,
            name=self.name(workspace["id"]),
            labels={"cloudlab.managed": "true", "cloudlab.workspace": workspace["id"]},
            user="1000:1000",
            working_dir="/workspace",
            read_only=True,
            volumes={self.name(workspace["id"]): {"bind": "/workspace", "mode": "rw"}},
            tmpfs={"/tmp": "rw,noexec,nosuid,size=64m,uid=1000,gid=1000"},
            network_mode="none",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit=f"{workspace['memory_mb']}m",
            memswap_limit=f"{workspace['memory_mb']}m",
            nano_cpus=int(workspace["cpu"] * 1_000_000_000),
            pids_limit=128,
            init=True,
            log_config=docker.types.LogConfig(type="local", config={"max-size": "5m", "max-file": "2"}),
        )

    def start(self, workspace):
        try:
            container = self.container(workspace["id"])
        except NotFound:
            container = self.create(workspace)
        container.start()

    def stop(self, workspace_id):
        try:
            self.container(workspace_id).stop(timeout=3)
        except NotFound:
            pass

    def delete(self, workspace_id):
        try:
            self.container(workspace_id).remove(force=True)
        except NotFound:
            pass
        try:
            self.client.volumes.get(self.name(workspace_id)).remove()
        except NotFound:
            pass

    def _agent(self, container, payload):
        command = ["timeout", "30", "python", "/opt/cloudlab/agent.py"]
        execution = self.client.api.exec_create(
            container.id, command, stdin=True, stdout=True, stderr=True, user="1000:1000"
        )
        attached = self.client.api.exec_start(execution["Id"], socket=True)
        sock = attached._sock
        sock.settimeout(35)
        try:
            sock.sendall(json.dumps(payload).encode() + b"\n")

            # Docker multiplexes stdout/stderr as 8-byte header + payload.
            def read_exact(count):
                data = bytearray()
                while len(data) < count:
                    chunk = sock.recv(count - len(data))
                    if not chunk:
                        return bytes(data)
                    data.extend(chunk)
                return bytes(data)

            output = bytearray()
            while True:
                header = read_exact(8)
                if len(header) != 8:
                    break
                size = int.from_bytes(header[4:], "big")
                if size > 30 * 1024 * 1024 or len(output) + size > 30 * 1024 * 1024:
                    raise RuntimeError("Workspace response exceeds the size limit.")
                output.extend(read_exact(size))
            result = json.loads(output)
            if "error" in result:
                raise RuntimeError(result["error"])
            return result
        except (ValueError, socket.timeout) as exc:
            raise RuntimeError("Workspace operation failed or timed out.") from exc
        finally:
            attached.close()

    def files(self, workspace_id, action, **kwargs):
        return self._agent(self.container(workspace_id), {"action": action, **kwargs})

    def _backup_operation(self, workspace_id, action, **kwargs):
        helper = self.client.containers.create(
            self.settings.runtime_image,
            command=["sleep", "infinity"],
            user="1000:1000",
            labels={"cloudlab.helper": "true"},
            network_mode="none",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit="384m",
            nano_cpus=500_000_000,
            pids_limit=32,
            volumes={
                self.name(workspace_id): {
                    "bind": "/workspace",
                    "mode": "ro" if action == "snapshot" else "rw",
                }
            },
        )
        try:
            helper.start()
            return self._agent(helper, {"action": action, **kwargs})
        finally:
            helper.remove(force=True)

    def backup(self, workspace_id):
        return base64.b64decode(self._backup_operation(workspace_id, "snapshot")["archive"])

    def restore(self, workspace_id, data):
        self._backup_operation(workspace_id, "restore", archive=base64.b64encode(data).decode())

    def terminal(self, workspace_id):
        container = self.container(workspace_id)
        execution = self.client.api.exec_create(
            container.id,
            ["bash", "--noprofile", "--norc"],
            stdin=True,
            tty=True,
            stdout=True,
            stderr=True,
            user="1000:1000",
            workdir="/workspace",
            environment={
                "TERM": "xterm-256color",
                "PS1": "\\[\\e[32m\\]learner@cloudlab\\[\\e[0m\\]:\\w\\$ ",
            },
        )
        attached = self.client.api.exec_start(execution["Id"], tty=True, socket=True)
        return execution["Id"], attached

    def resize(self, execution_id, cols, rows):
        self.client.api.exec_resize(execution_id, height=rows, width=cols)

    def metrics(self, workspace_id):
        stats = self.container(workspace_id).stats(stream=False, one_shot=True)
        cpu, previous = stats.get("cpu_stats", {}), stats.get("precpu_stats", {})
        delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - previous.get("cpu_usage", {}).get(
            "total_usage", 0
        )
        system = cpu.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
        cpu_percent = (delta / system * cpu.get("online_cpus", 1) * 100) if system > 0 else 0
        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_mb": round(stats.get("memory_stats", {}).get("usage", 0) / 1024**2, 1),
        }
