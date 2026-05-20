"""Production package (metrics, rate limiter, Docker/CLI support).

The high-level Fleet / AgentOrchestrator lives in production.agent_orchestrator
(addresses P1 architecture issues #80, #66, #39). Import directly:

    from production.agent_orchestrator import AgentOrchestrator, Fleet, ProxyPool
"""
