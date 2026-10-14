import base64
import importlib.util
import io
import tarfile

import pytest

spec = importlib.util.spec_from_file_location("agent", "runtime/agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(agent, "ROOT", root)
    return root


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "a/../../secret", ".", "", "a\x00b"])
def test_rejects_paths_outside_workspace(path):
    with pytest.raises(ValueError):
        agent.safe_path(path)


def test_rejects_symlink_parent(root, tmp_path):
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        agent.main({"action": "write", "path": "escape/secret", "content": "bad"})


def test_backup_restore_and_limits(root):
    agent.main({"action": "write", "path": "src/main.py", "content": "print('saved')"})
    backup = agent.snapshot()["archive"]
    agent.main({"action": "write", "path": "src/main.py", "content": "modified"})
    agent.main({"action": "write", "path": "new.txt", "content": "remove me"})
    agent.restore(backup)
    assert (root / "src/main.py").read_text() == "print('saved')"
    assert not (root / "new.txt").exists()
    with pytest.raises(ValueError):
        agent.main({"action": "write", "path": "big.txt", "content": "x" * 65537})


@pytest.mark.parametrize(
    "name,kind", [("../escape.txt", tarfile.REGTYPE), ("link", tarfile.SYMTYPE), ("device", tarfile.CHRTYPE)]
)
def test_rejects_malicious_archive_before_deleting_files(root, name, kind):
    (root / "original.txt").write_text("preserve me")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
        tar.addfile(member)
    with pytest.raises(ValueError):
        agent.restore(base64.b64encode(buffer.getvalue()))
    assert (root / "original.txt").read_text() == "preserve me"
