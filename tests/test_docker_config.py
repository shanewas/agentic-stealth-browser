"""
Tests for Docker configuration.
Addresses #15/#13: Docker hardening verification.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestDockerfile:
    """Dockerfile content tests."""

    def test_dockerfile_exists(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        assert dockerfile.exists(), "production/Dockerfile must exist"

    def test_dockerfile_uses_non_root_user(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "USER appuser" in content or "USER agent" in content, \
            "Dockerfile must run as non-root user"

    def test_dockerfile_has_healthcheck(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "HEALTHCHECK" in content, \
            "Dockerfile must have HEALTHCHECK instruction"

    def test_dockerfile_has_volumes(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "VOLUME" in content, \
            "Dockerfile must define VOLUME for persistent data"

    def test_dockerfile_has_entrypoint(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "ENTRYPOINT" in content, \
            "Dockerfile must define ENTRYPOINT"

    def test_dockerfile_installs_project(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "pip install" in content, \
            "Dockerfile must install the project"

    def test_dockerfile_creates_data_dirs(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "/data" in content, \
            "Dockerfile must create /data directories"

    def test_dockerfile_uses_slim_base(self):
        dockerfile = PROJECT_ROOT / "production" / "Dockerfile"
        content = dockerfile.read_text()
        assert "slim" in content.lower() or "alpine" in content.lower(), \
            "Dockerfile should use slim or alpine base image"


class TestDockerIgnore:
    """.dockerignore content tests."""

    def test_dockerignore_exists(self):
        dockerignore = PROJECT_ROOT / ".dockerignore"
        assert dockerignore.exists(), ".dockerignore must exist"

    def test_dockerignore_excludes_git(self):
        dockerignore = PROJECT_ROOT / ".dockerignore"
        content = dockerignore.read_text()
        assert ".git" in content, \
            ".dockerignore must exclude .git directory"

    def test_dockerignore_excludes_pycache(self):
        dockerignore = PROJECT_ROOT / ".dockerignore"
        content = dockerignore.read_text()
        assert "__pycache__" in content, \
            ".dockerignore must exclude __pycache__"

    def test_dockerignore_excludes_test_results(self):
        dockerignore = PROJECT_ROOT / ".dockerignore"
        content = dockerignore.read_text()
        assert "detection_results" in content or "*.json" in content, \
            ".dockerignore should exclude test result files"


class TestDockerCompose:
    """docker-compose.yml content tests."""

    def test_docker_compose_exists(self):
        compose = PROJECT_ROOT / "production" / "docker-compose.yml"
        assert compose.exists(), "production/docker-compose.yml must exist"

    def test_docker_compose_has_volumes(self):
        compose = PROJECT_ROOT / "production" / "docker-compose.yml"
        content = compose.read_text()
        assert "volumes:" in content, \
            "docker-compose.yml must define volumes"

    def test_docker_compose_has_healthcheck(self):
        compose = PROJECT_ROOT / "production" / "docker-compose.yml"
        content = compose.read_text()
        assert "healthcheck:" in content, \
            "docker-compose.yml must define healthcheck"

    def test_docker_compose_runs_as_non_root(self):
        compose = PROJECT_ROOT / "production" / "docker-compose.yml"
        content = compose.read_text()
        assert "user:" in content, \
            "docker-compose.yml should specify non-root user"


class TestHealthcheckScript:
    """docker-healthcheck.py tests."""

    def test_healthcheck_script_exists(self):
        script = PROJECT_ROOT / "production" / "docker-healthcheck.py"
        assert script.exists(), "production/docker-healthcheck.py must exist"

    def test_healthcheck_script_imports_core(self):
        script = PROJECT_ROOT / "production" / "docker-healthcheck.py"
        content = script.read_text()
        assert "AgentBrowser" in content, \
            "Healthcheck script must import AgentBrowser"

    def test_healthcheck_script_exits_with_code(self):
        script = PROJECT_ROOT / "production" / "docker-healthcheck.py"
        content = script.read_text()
        assert "sys.exit" in content, \
            "Healthcheck script must exit with status code"
