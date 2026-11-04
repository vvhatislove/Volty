import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

DEPLOY_SCRIPT = Path(__file__).parent.parent / "deploy" / "deploy.sh"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
    "compose build bot")
        [ ! -e broken_build ] ;;
    "compose ps -q bot")
        echo container ;;
    inspect*)
        if [ -e crashing_bot ]; then echo "true 3"; else echo "true 0"; fi ;;
esac
"""


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit(cwd: Path, name: str) -> str:
    (cwd / name).write_text(name)
    git(cwd, "add", ".")
    git(cwd, "commit", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@dataclass
class Server:
    checkout: Path
    source: Path
    first: str
    second: str
    docker_log: Path
    env: dict[str, str]

    def deploy(self, target: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.checkout / "deploy" / "deploy.sh")],
            cwd=self.checkout,
            env=self.env | {"SSH_ORIGINAL_COMMAND": target},
            capture_output=True,
            text=True,
        )

    def head(self) -> str:
        return git(self.checkout, "rev-parse", "HEAD")


@pytest.fixture
def server(tmp_path: Path) -> Server:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    (source / "deploy").mkdir()
    (source / "deploy" / "deploy.sh").write_text(DEPLOY_SCRIPT.read_text())
    first = commit(source, "first")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(source), str(checkout))
    second = commit(source, "second")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    docker_log = tmp_path / "docker.log"
    env = os.environ | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
        "DEPLOY_SETTLE_SECONDS": "0",
        "HOME": str(tmp_path),
    }
    return Server(checkout, source, first, second, docker_log, env)


def test_deploys_the_requested_commit(server: Server) -> None:
    result = server.deploy(server.second)

    assert result.returncode == 0, result.stderr
    assert server.head() == server.second
    assert "compose up -d bot" in server.docker_log.read_text()


def test_same_commit_changes_nothing(server: Server) -> None:
    result = server.deploy(server.first)

    assert result.returncode == 0
    assert not server.docker_log.exists()


@pytest.mark.parametrize("target", ["", "main", "rm -rf /", "abc123", "; reboot"])
def test_rejects_anything_but_a_full_sha(server: Server, target: str) -> None:
    result = server.deploy(target)

    assert result.returncode == 2
    assert server.head() == server.first
    assert not server.docker_log.exists()


def test_rejects_a_commit_that_is_not_on_main(server: Server) -> None:
    git(server.source, "checkout", "-q", "-b", "other")
    other = commit(server.source, "other")
    git(server.checkout, "fetch", "-q", "origin", "other")

    result = server.deploy(other)

    assert result.returncode == 2
    assert server.head() == server.first


def test_failed_build_returns_to_the_previous_commit(server: Server) -> None:
    (server.checkout / "broken_build").touch()

    result = server.deploy(server.second)

    assert result.returncode != 0
    assert server.head() == server.first


def test_crashing_bot_returns_to_the_previous_commit(server: Server) -> None:
    (server.checkout / "crashing_bot").touch()

    result = server.deploy(server.second)

    assert result.returncode == 1
    assert server.head() == server.first
    assert server.docker_log.read_text().count("compose up -d bot") == 2


def test_local_edits_are_kept_as_a_patch(server: Server) -> None:
    (server.checkout / "first").write_text("edited on the server")

    result = server.deploy(server.second)

    assert result.returncode == 0
    patches = list(Path(server.env["HOME"]).glob("volty-local-changes-*.patch"))
    assert len(patches) == 1
    assert "edited on the server" in patches[0].read_text()
