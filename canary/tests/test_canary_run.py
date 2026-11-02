"""Tests for scripts/canary_run.py publish behaviour."""

import asyncio
import fcntl
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_canary_run() -> Any:
    spec = importlib.util.spec_from_file_location(
        "canary_run", _REPO_ROOT / "scripts" / "canary_run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["canary_run"] = module
    spec.loader.exec_module(module)
    return module


class _FakeRunner:
    result: dict[str, Any] = {}

    async def run_all(self) -> dict[str, Any]:
        return dict(self.result)


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, module: Any, tmp_path: Path
) -> dict[str, Any]:
    calls: dict[str, Any] = {"badge": [], "dashboard": [], "readme": []}
    monkeypatch.setattr(module, "CanaryRunner", _FakeRunner)
    monkeypatch.setattr(
        module,
        "generate_badge",
        lambda history, path: calls["badge"].append((history, path)),
    )
    monkeypatch.setattr(
        module,
        "generate_dashboard",
        lambda history, path: calls["dashboard"].append((history, path)),
    )
    monkeypatch.setattr(
        module,
        "generate_readme",
        lambda history, path: calls["readme"].append((history, path)),
    )
    monkeypatch.setenv("CANARY_HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setenv("CANARY_DASHBOARD_PATH", str(tmp_path / "index.html"))
    monkeypatch.setenv("CANARY_BADGE_PATH", str(tmp_path / "badge.svg"))
    monkeypatch.setenv("CANARY_README_PATH", str(tmp_path / "README.md"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return calls


async def test_errored_run_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_canary_run()
    calls = _install_fakes(monkeypatch, module, tmp_path)
    _FakeRunner.result = {
        "ts": "2026-06-03T00:00:00Z",
        "version": "2.4.0",
        "score": None,
        "per_site": {},
        "duration_s": 1,
        "error": "runner crash: RuntimeError: boom",
    }
    with pytest.raises(SystemExit) as excinfo:
        await module.main()
    assert excinfo.value.code == 1
    assert not (tmp_path / "history.jsonl").exists()
    assert calls == {"badge": [], "dashboard": [], "readme": []}


async def test_valid_run_still_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_canary_run()
    calls = _install_fakes(monkeypatch, module, tmp_path)
    _FakeRunner.result = {
        "ts": "2026-06-03T00:00:00Z",
        "version": "2.4.0",
        "score": 100,
        "per_site": {"sannysoft": "pass"},
        "duration_s": 1,
        "error": None,
    }
    with pytest.raises(SystemExit) as excinfo:
        await module.main()
    assert excinfo.value.code == 0
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["score"] == 100
    assert len(calls["badge"]) == 1
    assert len(calls["dashboard"]) == 1
    assert len(calls["readme"]) == 1


def test_publish_blocks_while_lock_held_by_another_holder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_canary_run()
    calls = _install_fakes(monkeypatch, module, tmp_path)
    _FakeRunner.result = {
        "ts": "2026-06-03T00:00:00Z",
        "version": "2.4.0",
        "score": 100,
        "per_site": {"sannysoft": "pass"},
        "duration_s": 1,
        "error": None,
    }
    lock_path = tmp_path / "history.jsonl.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    codes: list[Any] = []

    def _run() -> None:
        try:
            asyncio.run(module.main())
        except SystemExit as exc:
            codes.append(exc.code)

    thread = threading.Thread(target=_run)
    thread.start()
    try:
        time.sleep(0.5)
        # Blocked on the lock: nothing appended or published yet.
        assert thread.is_alive()
        assert not (tmp_path / "history.jsonl").exists()
        assert calls == {"badge": [], "dashboard": [], "readme": []}
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert codes == [0]
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert len(calls["badge"]) == 1
