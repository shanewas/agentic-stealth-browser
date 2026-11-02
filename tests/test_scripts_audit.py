"""Regression tests for scripts/ audit fixes.

Scripts must not report success for work that did not happen.
Script modules are loaded by file path (scripts/ is not a package).
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scripts_audit_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_file(filename, modname):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migrate = _load_script("migrate_v1_to_v2")
backup = _load_script("backup_sessions")
health = _load_script("health_check")
perf = _load_script("perf_benchmark")

from workflows.schema import load_workflow, validate_workflow  # noqa: E402


# ---------------------------------------------------------------- migration


def _write_yaml(path, data):
    path.write_text(yaml.dump(data, sort_keys=False))
    return str(path)


def test_migrated_navigate_step_validates_with_real_schema(tmp_path):
    src = _write_yaml(
        tmp_path / "v1.yaml",
        {
            "name": "demo",
            "description": "demo workflow",
            "steps": [
                {
                    "type": "navigate",
                    "url": "https://example.com",
                    "description": "go to example",
                },
                {"type": "click", "selector": "#btn"},
            ],
        },
    )
    migrated = migrate.migrate_workflow_yaml(src, str(tmp_path / "v2.yaml"))

    step = migrated["steps"][0]
    assert step == {"type": "navigate", "url": "https://example.com"}
    result = validate_workflow(load_workflow(migrated))
    assert result.valid, result.errors
    # The written file loads and validates through the real loader too.
    result = validate_workflow(load_workflow(str(tmp_path / "v2.yaml")))
    assert result.valid, result.errors


def test_validate_catches_broken_migration_via_real_validator(tmp_path, capsys):
    src = _write_yaml(
        tmp_path / "broken.yaml",
        {"name": "broken", "steps": [{"type": "navigate"}]},  # missing url
    )
    out = tmp_path / "out.yaml"
    code = migrate.main(
        ["--validate", "--input", src, "--output", str(out), "--json"]
    )
    assert code == 1
    assert not out.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert any("url" in issue for issue in payload["issues"])


def test_same_input_output_path_refused_and_input_untouched(tmp_path):
    src = tmp_path / "wf.yaml"
    original = "name: demo\nsteps:\n  - type: navigate\n    url: https://example.com\n"
    src.write_text(original)
    for extra in ([], ["--validate"]):
        code = migrate.main([*extra, "--input", str(src), "--output", str(src)])
        assert code != 0
        assert src.read_text() == original


def test_unknown_top_level_key_is_carried_through(tmp_path):
    src = _write_yaml(
        tmp_path / "v1.yaml",
        {
            "name": "demo",
            "custom_top_level": "keep-me",
            "steps": [{"type": "navigate", "url": "https://example.com"}],
        },
    )
    migrated = migrate.migrate_workflow_yaml(src)
    # L10 choice: carried through (schema tolerates unknown top-level keys).
    assert migrated["custom_top_level"] == "keep-me"
    assert validate_workflow(load_workflow(migrated)).valid


# ------------------------------------------------------------------- backup


def _fake_repo(tmp_path, with_data=True):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "backup_sessions.py", repo / "scripts")
    if with_data:
        (repo / "sessions").mkdir()
        (repo / "sessions" / "cookies.json").write_text('{"a": 1}')
    out = tmp_path / "out"
    out.mkdir()
    wrong_cwd = tmp_path / "elsewhere"
    wrong_cwd.mkdir()
    return repo, out, wrong_cwd


def _run_backup(repo, out, cwd):
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "backup_sessions.py"), str(out)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_backup_archives_repo_sessions_from_wrong_cwd(tmp_path):
    repo, out, wrong_cwd = _fake_repo(tmp_path)
    proc = _run_backup(repo, out, wrong_cwd)
    assert proc.returncode == 0, proc.stderr
    archives = list(out.glob("backup-sessions-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as tar:
        assert "sessions/cookies.json" in tar.getnames()


def test_backup_without_sources_fails_and_creates_no_archive(tmp_path):
    repo, out, wrong_cwd = _fake_repo(tmp_path, with_data=False)
    proc = _run_backup(repo, out, wrong_cwd)
    assert proc.returncode != 0
    assert list(out.iterdir()) == []


def test_backup_two_runs_in_same_second_both_intact(tmp_path):
    repo, out, wrong_cwd = _fake_repo(tmp_path)
    for _ in range(2):
        proc = _run_backup(repo, out, wrong_cwd)
        assert proc.returncode == 0, proc.stderr
    archives = sorted(out.glob("backup-sessions-*.tar.gz"))
    assert len(archives) == 2
    for archive in archives:
        with tarfile.open(archive) as tar:
            assert "sessions/cookies.json" in tar.getnames()


# ------------------------------------------------------------------- health


def _healthy_checks(monkeypatch, **overrides):
    checks = {
        "check_mcp_server": lambda: {"running": True, "details": "ok"},
        "check_workflow_library": lambda: {
            "accessible": True,
            "workflow_count": 0,
            "valid": 0,
            "invalid": 0,
            "errors": [],
        },
        "check_bridge": lambda: {
            "status": "running",
            "port": 9222,
            "cloudflared_installed": True,
            "service_configured": True,
        },
        "check_disk": lambda: {"warning": False},
        "check_memory": lambda: {"warning": False},
    }
    checks.update(overrides)
    for name, fn in checks.items():
        monkeypatch.setattr(health, name, fn)


def _run_main(capsys):
    with pytest.raises(SystemExit) as excinfo:
        health.main()
    return excinfo.value.code, json.loads(capsys.readouterr().out)


def test_bridge_inactive_service_is_not_configured(monkeypatch):
    monkeypatch.setattr(health.sys, "platform", "linux")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=3, stdout="inactive\n", stderr=""
        ),
    )
    real_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: False
        if "stealth-rbb" in str(self)
        else real_exists(self),
    )
    result = health.check_bridge()
    assert result["service_configured"] is False


def test_bridge_not_configured_flows_into_overall_status(monkeypatch, capsys):
    _healthy_checks(
        monkeypatch,
        check_bridge=lambda: {
            "status": "not_configured",
            "port": 9222,
            "cloudflared_installed": False,
            "service_configured": False,
        },
    )
    code, report = _run_main(capsys)
    assert code == 1
    assert report["status"] != "healthy"
    assert any("Bridge" in issue for issue in report["issues"])


def test_check_error_dict_counts_as_unhealthy(monkeypatch, capsys):
    _healthy_checks(monkeypatch, check_disk=lambda: {"error": "disk boom"})
    code, report = _run_main(capsys)
    assert code == 1
    assert report["status"] != "healthy"
    assert any("disk" in issue for issue in report["issues"])


def test_check_raising_counts_as_unhealthy(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("mem boom")

    _healthy_checks(monkeypatch, check_memory=_boom)
    code, report = _run_main(capsys)
    assert code == 1
    assert any("memory" in issue for issue in report["issues"])


def test_unparseable_port_is_json_failure_not_crash(monkeypatch, capsys):
    monkeypatch.setenv("STEALTH_RBB_PORT", "abc")
    _healthy_checks(monkeypatch, check_bridge=health.check_bridge)
    code, report = _run_main(capsys)
    assert code == 1
    assert "STEALTH_RBB_PORT" in report["checks"]["bridge"]["error"]
    assert any("bridge" in issue for issue in report["issues"])


# --------------------------------------------------------------- benchmark


def _raise():
    raise RuntimeError("always fails")


def test_always_raising_benchmark_is_failed_not_zero_ms():
    bench = perf.PerfBenchmark(iterations=3, warmup=0)
    result = bench._run("always_fails", _raise)
    assert result.failed
    data = result.to_dict()
    assert data["status"] == "FAILED"
    assert data["mean_ms"] is None
    assert bench.has_failures


async def test_benchmark_main_exits_nonzero_when_any_benchmark_fails(
    monkeypatch, capsys
):
    async def fake_bench_all(self):
        self._run("always_fails", _raise)
        return self.report()

    monkeypatch.setattr(perf.PerfBenchmark, "bench_all", fake_bench_all)
    code = await perf.main(["--iterations", "3", "--warmup", "0", "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["status"] == "FAILED"


def test_working_benchmark_report_shape_unchanged():
    bench = perf.PerfBenchmark(iterations=3, warmup=0)
    result = bench._run("works", lambda: None)
    assert not result.failed
    assert not bench.has_failures
    data = result.to_dict()
    assert set(data) == {
        "name",
        "iterations",
        "mean_ms",
        "median_ms",
        "p95_ms",
        "p99_ms",
        "stddev_ms",
        "min_ms",
        "max_ms",
    }
    assert isinstance(data["mean_ms"], (int, float))


# ------------------------------------------------------------------ hn-demo


class _FakeDemoBrowser:
    launches = 0
    goto_results: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        type(self).launches += 1  # context manager owns the launch
        return self

    async def __aexit__(self, *exc):
        return False

    async def launch(self, **kwargs):
        type(self).launches += 1
        raise RuntimeError("already has an active browser/context")

    async def safe_goto(self, url, **kwargs):
        return type(self).goto_results.pop(0)


def _install_demo_fakes(monkeypatch):
    import types

    monkeypatch.setitem(
        sys.modules,
        "core.agent_browser",
        SimpleNamespace(AgentBrowser=_FakeDemoBrowser),
    )
    monkeypatch.setitem(
        sys.modules,
        "stealth.advanced_stealth",
        SimpleNamespace(get_stealth_script=lambda *a, **k: "x" * 200),
    )
    cli = types.ModuleType("production.cli")
    monkeypatch.setitem(sys.modules, "production.cli", cli)
    _FakeDemoBrowser.launches = 0
    _FakeDemoBrowser.goto_results = [True, True]


async def test_hn_demo_single_launch_and_success(monkeypatch, capsys):
    hn = _load_file("hn-demo.py", "scripts_audit_hn_demo")
    _install_demo_fakes(monkeypatch)
    await hn.main()
    assert _FakeDemoBrowser.launches == 1
    out = capsys.readouterr().out
    assert "production.cli loaded" in out
    assert "All systems operational" in out


async def test_hn_demo_blocked_navigation_exits_nonzero(monkeypatch, capsys):
    hn = _load_file("hn-demo.py", "scripts_audit_hn_demo_blocked")
    _install_demo_fakes(monkeypatch)
    _FakeDemoBrowser.goto_results = [False]
    with pytest.raises(SystemExit) as excinfo:
        await hn.main()
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "All systems operational" not in out
    assert "failed/blocked" in out


async def test_hn_demo_import_failure_is_honest(monkeypatch, capsys):
    hn = _load_file("hn-demo.py", "scripts_audit_hn_demo_importfail")
    _install_demo_fakes(monkeypatch)
    monkeypatch.setitem(sys.modules, "production.cli", None)
    with pytest.raises(SystemExit) as excinfo:
        await hn.main()
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "production.cli loaded" not in out
    assert "Import failed" in out


# ------------------------------------------------------------ stealth eval


class _FakeEvalBrowser:
    instances: list = []
    goto_ok = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.warm_ups: list = []
        type(self).instances.append(self)

    async def launch(self, **kwargs):
        self.launch_kwargs = kwargs

    async def safe_goto(self, url, warm_up=True, **kwargs):
        self.warm_ups.append(warm_up)
        return type(self).goto_ok

    async def close(self):
        pass


def _install_eval_fake(monkeypatch, goto_ok=True):
    _FakeEvalBrowser.instances = []
    _FakeEvalBrowser.goto_ok = goto_ok
    monkeypatch.setitem(
        sys.modules, "core.agent_browser", SimpleNamespace(AgentBrowser=_FakeEvalBrowser)
    )


async def test_evaluator_conditions_differ_only_in_warm_up(monkeypatch):
    ev = _load_file("evaluate_stealth.py", "scripts_audit_evaluate_stealth")
    _install_eval_fake(monkeypatch)
    evaluator = ev.StealthEvaluator(seed=1)
    await evaluator.run_warm_navigate("https://example.com")
    await evaluator.run_cold_navigate("https://example.com")
    assert [i.warm_ups for i in _FakeEvalBrowser.instances] == [[True], [False]]
    report = evaluator.generate_report()
    assert set(report) >= {"warm", "cold"}
    assert "patched" not in report and "baseline" not in report
    assert report["stealth_comparison_claimed"] is False
    assert "warm-up" in report["comparison"]["note"]
    assert "not stealth effectiveness" in report["comparison"]["note"]


async def test_evaluator_iterations_zero_rejected(monkeypatch):
    ev = _load_file("evaluate_stealth.py", "scripts_audit_evaluate_iter0")
    _install_eval_fake(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        await ev.main(["--iterations", "0"])
    assert excinfo.value.code != 0


def test_evaluator_empty_stats_have_full_shape():
    ev = _load_file("evaluate_stealth.py", "scripts_audit_evaluate_empty")
    report = ev.StealthEvaluator(seed=1).generate_report()
    for stats in (report["warm"], report["cold"]):
        assert stats["count"] == 0
        assert stats["detection_rate"] == 0.0
        assert stats["avg_load_time_ms"] == 0.0


async def test_evaluator_all_failed_exits_nonzero(monkeypatch, capsys):
    ev = _load_file("evaluate_stealth.py", "scripts_audit_evaluate_allfail")
    _install_eval_fake(monkeypatch, goto_ok=False)
    code = await ev.main(["--iterations", "1", "--urls", "https://example.com"])
    assert code == 1
    json.loads(capsys.readouterr().out)


# ------------------------------------------------------------------- gifs


def test_make_gif_expect_script_contains_real_output_path(tmp_path):
    mod = _load_file("make-gif.py", "scripts_audit_make_gif")
    target = tmp_path / "recording.cast"
    script = mod.build_expect_script(target)
    assert str(target) in script
    assert "{output}" not in script
    expect_path = mod.write_expect_script(target)
    try:
        assert expect_path.exists()
        assert expect_path.name != "hn-demo.expect"
        assert expect_path.stat().st_mode & 0o777 != 0o755
    finally:
        expect_path.unlink(missing_ok=True)


def test_make_gif_failure_returns_nonzero(tmp_path):
    mod = _load_file("make-gif.py", "scripts_audit_make_gif_fail")

    def failing_runner(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    code = mod.main(
        runner=failing_runner,
        cast_file=tmp_path / "x.cast",
        gif_path=tmp_path / "x.gif",
        repo=tmp_path,
    )
    assert code == 1


def test_make_gif_missing_cast_returns_nonzero(tmp_path):
    mod = _load_file("make-gif.py", "scripts_audit_make_gif_nocast")

    def ok_runner(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    code = mod.main(
        runner=ok_runner,
        cast_file=tmp_path / "missing.cast",
        gif_path=tmp_path / "x.gif",
        repo=tmp_path,
    )
    assert code == 1


def test_generate_demo_gif_output_path_is_repo_relative():
    mod = _load_file("generate-demo-gif.py", "scripts_audit_gen_gif_path")
    assert mod.OUTPUT_PATH == ROOT / "assets" / "hn-demo.gif"


def test_generate_demo_gif_pillow_bootstrap_ordering(monkeypatch):
    mod = _load_file("generate-demo-gif.py", "scripts_audit_gen_gif_boot")
    monkeypatch.setattr(mod, "Image", None)
    events: list = []
    attempts = {"n": 0}

    def importer():
        events.append("import")
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ImportError("no Pillow")
        return (object(), object(), object())

    def installer():
        events.append("install")
        return SimpleNamespace(returncode=0)

    mod._ensure_pillow(importer=importer, installer=installer)
    assert events == ["import", "install", "import"]


def test_generate_demo_gif_pillow_install_failure_is_loud(monkeypatch):
    mod = _load_file("generate-demo-gif.py", "scripts_audit_gen_gif_bootfail")
    monkeypatch.setattr(mod, "Image", None)

    def importer():
        raise ImportError("no Pillow")

    def installer():
        return SimpleNamespace(returncode=1)

    with pytest.raises(SystemExit):
        mod._ensure_pillow(importer=importer, installer=installer)
