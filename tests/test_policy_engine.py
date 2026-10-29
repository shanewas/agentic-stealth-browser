"""PolicyEngine fixes: domain normalization, missing-policy fail-closed,
and leaf-step (conditional / nested / variable) checks at the replay gate."""

import pytest

from production.approval_gate import is_sensitive_action
from production.mcp_handlers import _expand_replay_steps
from production.mcp_server import StealthMCPServer, ToolError
from production.policy_engine import DomainRule, Policy, PolicyEngine


def _engine_with(policy: Policy) -> PolicyEngine:
    engine = PolicyEngine()
    engine.policies[policy.name] = policy
    engine.set_active(policy.name)
    return engine


class TestDomainNormalization:
    @pytest.mark.parametrize(
        "url",
        [
            "https://blocked.example/path",
            "https://blocked.example./path",
            "https://BLOCKED.example:443/path",
            "blocked.example/path",
            "blocked.example",
            "BLOCKED.example:8443/path",
        ],
    )
    def test_blocked_domain_spellings_are_blocked(self, url):
        policy = Policy(
            name="p",
            domain_rules=[DomainRule(domain="blocked.example", allow=False)],
        )
        assert policy.is_domain_allowed(url) is False

    def test_exact_host_semantics_kept(self):
        policy = Policy(
            name="p",
            domain_rules=[DomainRule(domain="blocked.example", allow=False)],
        )
        # A rule for blocked.example does NOT cover www.blocked.example.
        assert policy.is_domain_allowed("https://www.blocked.example/path") is True

    def test_allowed_rules_behave_symmetrically(self):
        policy = Policy(
            name="p",
            default_allow=False,
            domain_rules=[DomainRule(domain="EXAMPLE.com.", allow=True)],
        )
        assert policy.is_domain_allowed("https://example.com/path") is True
        assert policy.is_domain_allowed("example.com:443/path") is True
        assert policy.is_domain_allowed("https://www.example.com/path") is False
        assert policy.is_domain_allowed("https://other.example/path") is False

    def test_rule_domains_normalized_at_load(self, tmp_path):
        (tmp_path / "p.yaml").write_text(
            "name: loaded\n"
            "domain_rules:\n"
            "  - domain: 'BLOCKED.example.:443'\n"
            "    allow: false\n"
        )
        engine = PolicyEngine()
        assert engine.load_policies(str(tmp_path)) == 1
        policy = engine.policies["loaded"]
        assert policy.domain_rules[0].domain == "blocked.example"
        assert policy.is_domain_allowed("blocked.example/path") is False


class TestMissingPolicy:
    def test_unknown_policy_name_denied(self):
        engine = PolicyEngine()
        result = engine.check_step("navigate", "https://example.com", policy_name="nope")
        assert result["allowed"] is False
        assert result["approval_required"] is True
        assert "nope" in result["reason"]

    def test_missing_active_policy_denied(self):
        engine = PolicyEngine()
        engine.active_policy = "ghost"
        result = engine.check_step("navigate", "https://example.com")
        assert result["allowed"] is False
        assert "ghost" in result["reason"]

    def test_set_active_missing_raises(self):
        engine = PolicyEngine()
        with pytest.raises(ValueError, match="not loaded"):
            engine.set_active("nope")
        # The request is retained, so a caller that catches the error does
        # not silently fall back to fail-open enforcement.
        assert engine.check_step("navigate", "https://example.com")["allowed"] is False

    def test_set_active_loaded_policy(self):
        engine = _engine_with(Policy(name="real"))
        assert engine.active_policy == "real"

    def test_no_policy_at_all_still_allows(self):
        engine = PolicyEngine()
        result = engine.check_step("navigate", "https://anything.example/path")
        assert result == {
            "allowed": True,
            "reason": "ok",
            "approval_required": False,
        }

    def test_loaded_policy_behaves_as_before(self):
        engine = _engine_with(
            Policy(name="strict", blocked_step_types={"execute_js"})
        )
        assert engine.check_step("execute_js", "")["allowed"] is False
        assert engine.check_step("navigate", "https://example.com")["allowed"] is True

    def test_unresolved_variable_url_fails_closed_only_with_policy(self):
        engine = _engine_with(Policy(name="strict"))
        result = engine.check_step("navigate", "https://{{host}}/path")
        assert result["allowed"] is False
        assert result["approval_required"] is True
        # Unconfigured engine keeps its documented fail-open result.
        assert PolicyEngine().check_step("navigate", "https://{{host}}/path")["allowed"] is True


def _replay_server(tmp_path, policy: Policy, monkeypatch) -> StealthMCPServer:
    monkeypatch.delenv("STEALTH_MCP_POLICY", raising=False)
    server = StealthMCPServer()
    library = tmp_path / "library"
    library.mkdir(parents=True, exist_ok=True)
    server._workflow_library_root = library
    server._policy_engine = _engine_with(policy)
    return server


async def _replay(server, filename, variables=None):
    return await server._tool_stealth_replay(
        {"filename": filename, "session_name": "s", "variables": variables or {}}
    )


class TestReplayGateLeafSteps:
    @pytest.mark.asyncio
    async def test_conditional_wrapped_execute_js_blocked(self, tmp_path, monkeypatch):
        server = _replay_server(
            tmp_path, Policy(name="strict", blocked_step_types={"execute_js"}), monkeypatch
        )
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'true'\n"
            "    steps:\n"
            "      - type: execute_js\n"
            "        code: '1'\n"
            "    else_steps:\n"
            "      - type: execute_js\n"
            "        code: '2'\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "w.yaml")
        assert exc.value.error_code == "MCP_POLICY_DENIED"
        assert exc.value.details["step_type"] == "execute_js"

    @pytest.mark.asyncio
    async def test_conditional_wrapped_execute_js_pends_for_approval(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
        server = _replay_server(
            tmp_path,
            Policy(name="strict", require_approval_for=["execute_js"]),
            monkeypatch,
        )
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'true'\n"
            "    steps:\n"
            "      - type: execute_js\n"
            "        code: '1'\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "w.yaml")
        assert exc.value.error_code == "MCP_APPROVAL_REQUIRED"
        assert exc.value.details["step_type"] == "execute_js"

    @pytest.mark.asyncio
    async def test_nested_workflow_blocked_step_caught(self, tmp_path, monkeypatch):
        server = _replay_server(
            tmp_path, Policy(name="strict", blocked_step_types={"execute_js"}), monkeypatch
        )
        (server._workflow_library_root / "inner.yaml").write_text(
            "name: inner\n"
            "steps:\n"
            "  - type: execute_js\n"
            "    code: '1'\n"
        )
        (server._workflow_library_root / "outer.yaml").write_text(
            "name: outer\n"
            "steps:\n"
            "  - type: run_workflow\n"
            "    path: inner.yaml\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "outer.yaml")
        assert exc.value.error_code == "MCP_POLICY_DENIED"
        assert exc.value.details["step_type"] == "execute_js"

    @pytest.mark.asyncio
    async def test_variable_resolved_blocked_domain_caught(self, tmp_path, monkeypatch):
        server = _replay_server(
            tmp_path,
            Policy(
                name="strict",
                domain_rules=[DomainRule(domain="blocked.example", allow=False)],
            ),
            monkeypatch,
        )
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: navigate\n"
            "    url: 'https://{{host}}/path'\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "w.yaml", variables={"host": "blocked.example"})
        assert exc.value.error_code == "MCP_POLICY_DENIED"

    @pytest.mark.asyncio
    async def test_unresolvable_nested_workflow_fails_closed_with_policy(
        self, tmp_path, monkeypatch
    ):
        server = _replay_server(tmp_path, Policy(name="strict"), monkeypatch)
        (server._workflow_library_root / "outer.yaml").write_text(
            "name: outer\n"
            "steps:\n"
            "  - type: run_workflow\n"
            "    path: missing.yaml\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "outer.yaml")
        assert exc.value.error_code == "MCP_POLICY_DENIED"


class TestConditionalConditionGate:
    """H2: a conditional's condition is JS the player evaluates, so the
    expansion emits it as an execute_js leaf for the policy/approval gate."""

    @pytest.mark.asyncio
    async def test_condition_only_js_blocked_by_execute_js_policy(
        self, tmp_path, monkeypatch
    ):
        server = _replay_server(
            tmp_path, Policy(name="strict", blocked_step_types={"execute_js"}), monkeypatch
        )
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'document.title'\n"
            "    steps:\n"
            "      - type: wait\n"
            "        ms: 1\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "w.yaml")
        assert exc.value.error_code == "MCP_POLICY_DENIED"
        assert exc.value.details["step_type"] == "execute_js"

    @pytest.mark.asyncio
    async def test_condition_only_js_pends_for_approval(self, tmp_path, monkeypatch):
        monkeypatch.delenv("STEALTH_APPROVAL_MODE", raising=False)
        server = _replay_server(
            tmp_path,
            Policy(name="strict", require_approval_for=["execute_js"]),
            monkeypatch,
        )
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'document.title'\n"
            "    steps:\n"
            "      - type: wait\n"
            "        ms: 1\n"
        )
        assert is_sensitive_action("execute_js") is True
        with pytest.raises(ToolError) as exc:
            await _replay(server, "w.yaml")
        assert exc.value.error_code == "MCP_APPROVAL_REQUIRED"
        assert exc.value.details["step_type"] == "execute_js"

    @pytest.mark.asyncio
    async def test_condition_only_js_allowed_when_js_not_blocked(
        self, tmp_path, monkeypatch
    ):
        from types import SimpleNamespace

        server = _replay_server(tmp_path, Policy(name="open"), monkeypatch)
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'document.title'\n"
            "    steps:\n"
            "      - type: wait\n"
            "        ms: 1\n"
        )
        server._sessions["s"] = object()

        class _FakePlayer:
            def __init__(self, browser):
                self.browser = browser

            async def execute(self, workflow, runtime_vars=None):
                return SimpleNamespace(
                    success=True,
                    steps_executed=1,
                    total_steps=1,
                    failed_step=None,
                    failed_step_type=None,
                    error_message=None,
                    execution_time=0.0,
                    summary="ok",
                )

        monkeypatch.setattr("workflows.player.WorkflowPlayer", _FakePlayer)
        result = await _replay(server, "w.yaml")
        assert result["success"] is True

    @pytest.mark.parametrize("condition", ["", "   "])
    def test_trivial_condition_emits_no_js_leaf(self, tmp_path, condition):
        steps = [
            {
                "type": "conditional",
                "condition": condition,
                "steps": [{"type": "wait", "ms": 1}],
            }
        ]
        expanded = _expand_replay_steps(steps, {}, tmp_path, tmp_path)
        assert [s["type"] for s in expanded] == ["conditional", "wait"]
        assert all(s["type"] != "execute_js" for s in expanded)

    def test_branch_steps_still_expand_after_condition_leaf(self, tmp_path):
        steps = [
            {
                "type": "conditional",
                "condition": "document.title",
                "steps": [{"type": "click", "selector": "#ok"}],
                "else_steps": [
                    {"type": "navigate", "url": "https://example.com"}
                ],
            }
        ]
        expanded = _expand_replay_steps(steps, {}, tmp_path, tmp_path)
        assert [s["type"] for s in expanded] == [
            "conditional",
            "execute_js",
            "click",
            "navigate",
        ]
        assert expanded[1]["params"] == {"code": "document.title"}
        assert expanded[1]["url"] == ""
        assert expanded[1]["error"] is None
        assert expanded[3]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_branch_step_still_checked_when_condition_trivial(
        self, tmp_path, monkeypatch
    ):
        server = _replay_server(
            tmp_path, Policy(name="strict", blocked_step_types={"execute_js"}), monkeypatch
        )
        (server._workflow_library_root / "w.yaml").write_text(
            "name: w\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: ''\n"
            "    steps:\n"
            "      - type: wait\n"
            "        ms: 1\n"
            "    else_steps:\n"
            "      - type: execute_js\n"
            "        code: '1'\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "w.yaml")
        assert exc.value.error_code == "MCP_POLICY_DENIED"
        assert exc.value.details["step_type"] == "execute_js"

    @pytest.mark.asyncio
    async def test_nested_workflow_conditional_condition_blocked(
        self, tmp_path, monkeypatch
    ):
        server = _replay_server(
            tmp_path, Policy(name="strict", blocked_step_types={"execute_js"}), monkeypatch
        )
        (server._workflow_library_root / "inner.yaml").write_text(
            "name: inner\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'document.title'\n"
            "    steps:\n"
            "      - type: wait\n"
            "        ms: 1\n"
        )
        (server._workflow_library_root / "outer.yaml").write_text(
            "name: outer\n"
            "steps:\n"
            "  - type: run_workflow\n"
            "    path: inner.yaml\n"
        )
        with pytest.raises(ToolError) as exc:
            await _replay(server, "outer.yaml")
        assert exc.value.error_code == "MCP_POLICY_DENIED"
        assert exc.value.details["step_type"] == "execute_js"

    def test_condition_leaves_in_cycle_safe_nested_expansion(self, tmp_path):
        (tmp_path / "a.yaml").write_text(
            "name: a\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'document.title'\n"
            "    steps:\n"
            "      - type: run_workflow\n"
            "        path: b.yaml\n"
        )
        (tmp_path / "b.yaml").write_text(
            "name: b\n"
            "steps:\n"
            "  - type: conditional\n"
            "    condition: 'document.cookie'\n"
            "    steps:\n"
            "      - type: run_workflow\n"
            "        path: a.yaml\n"
        )
        steps = [{"type": "run_workflow", "path": "a.yaml"}]
        expanded = _expand_replay_steps(steps, {}, tmp_path, tmp_path)
        js_codes = [
            s["params"]["code"] for s in expanded if s["type"] == "execute_js"
        ]
        assert js_codes == ["document.title", "document.cookie"]
        errors = [s["error"] for s in expanded if s.get("error")]
        assert any("cycle" in e for e in errors)
