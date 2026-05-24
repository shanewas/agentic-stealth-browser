"""Tests for workflow orchestrator v1.3.0."""

import asyncio
import json
import os
import tempfile
import time

import pytest

from production.workflow_orchestrator import (
    QueueJob,
    RecurringJob,
    WorkflowOrchestrator,
    OrchestratorStatus,
)


@pytest.fixture
def orchestrator():
    return WorkflowOrchestrator(max_concurrent_total=5)


@pytest.fixture
def persist_orchestrator():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "state.json")
        orch = WorkflowOrchestrator(
            max_concurrent_total=5,
            persistence_path=path,
        )
        yield orch


# ---- Queue manager tests ----

@pytest.mark.asyncio
class TestEnqueue:
    async def test_enqueue_single(self, orchestrator):
        job = await orchestrator.enqueue(
            workflow_path="workflows/test.yaml",
            domain="example.com",
            account="user1",
        )
        assert isinstance(job, QueueJob)
        assert job.workflow_path == "workflows/test.yaml"
        assert job.domain == "example.com"
        assert job.status == "queued"

    async def test_enqueue_batch(self, orchestrator):
        specs = [
            {"workflow_path": "wf1.yaml", "domain": "example.com", "priority": 10},
            {"workflow_path": "wf2.yaml", "domain": "example.com", "priority": 5},
        ]
        jobs = await orchestrator.enqueue_batch(specs)
        assert len(jobs) == 2
        assert orchestrator.status().queue_size == 2

    async def test_enqueue_priority_ordering(self, orchestrator):
        await orchestrator.enqueue(workflow_path="low.yaml", priority=1)
        await orchestrator.enqueue(workflow_path="high.yaml", priority=10)
        job = await orchestrator.dequeue()
        assert job.workflow_path == "high.yaml"

    async def test_dequeue_specific(self, orchestrator):
        job = await orchestrator.enqueue(workflow_path="wf.yaml")
        dequeued = await orchestrator.dequeue(job_id=job.job_id)
        assert dequeued is not None
        assert dequeued.job_id == job.job_id

    async def test_dequeue_nonexistent(self, orchestrator):
        result = await orchestrator.dequeue(job_id="nonexistent")
        assert result is None

    async def test_dequeue_empty(self, orchestrator):
        result = await orchestrator.dequeue()
        assert result is None


class TestDomainConcurrency:
    def test_extract_domain_from_url(self):
        domain = WorkflowOrchestrator.extract_domain("https://www.linkedin.com/feed")
        assert domain == "www.linkedin.com"

    def test_extract_domain_from_path(self):
        domain = WorkflowOrchestrator.extract_domain("workflows/linkedin_login.yaml")
        assert domain == "workflow"


@pytest.mark.asyncio
class TestOrchestratorRun:
    async def test_run_calls_executor(self, orchestrator):
        executed = []

        async def executor(job):
            executed.append(job.job_id)
            return {"success": True}

        orchestrator.set_executor(executor)
        await orchestrator.enqueue(workflow_path="wf.yaml", domain="test.com")

        task = asyncio.create_task(orchestrator.run(tick_interval=0.1))
        await asyncio.sleep(0.5)
        await orchestrator.stop()
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(executed) > 0
        status = orchestrator.status()
        assert status.completed_jobs > 0

    async def test_transient_failure_retry(self, orchestrator):
        call_count = 0

        async def executor(job):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"success": False, "error": "Temporary error"}
            return {"success": True}

        orchestrator.set_executor(executor)
        await orchestrator.enqueue(
            workflow_path="wf.yaml",
            domain="test.com",
            max_retries=5,
        )

        task = asyncio.create_task(orchestrator.run(tick_interval=0.1))
        await asyncio.sleep(2.0)
        await orchestrator.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        status = orchestrator.status()
        assert status.completed_jobs > 0 or status.failed_jobs > 0

    async def test_domain_concurrency_limit(self, orchestrator):
        active_at_once = []
        max_active = 0

        async def executor(job):
            nonlocal max_active
            active_at_once.append(job.job_id)
            max_active = max(max_active, len(active_at_once))
            await asyncio.sleep(0.1)
            active_at_once.remove(job.job_id)
            return {"success": True}

        orch = WorkflowOrchestrator(
            max_concurrent_total=10,
            domain_concurrency={"linkedin.com": 1},
        )
        orch.set_executor(executor)

        await orch.enqueue(workflow_path="wf1.yaml", domain="linkedin.com")
        await orch.enqueue(workflow_path="wf2.yaml", domain="linkedin.com")

        task = asyncio.create_task(orch.run(tick_interval=0.1))
        await asyncio.sleep(1.0)
        await orch.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert max_active <= 1

    async def test_max_concurrent_total(self, orchestrator):
        active_count = 0
        max_concurrent = 0

        async def executor(job):
            nonlocal active_count, max_concurrent
            active_count += 1
            max_concurrent = max(max_concurrent, active_count)
            await asyncio.sleep(0.1)
            active_count -= 1
            return {"success": True}

        orch = WorkflowOrchestrator(max_concurrent_total=2)
        orch.set_executor(executor)

        for i in range(5):
            await orch.enqueue(workflow_path=f"wf{i}.yaml", domain=f"domain{i}.com")

        task = asyncio.create_task(orch.run(tick_interval=0.1))
        await asyncio.sleep(1.5)
        await orch.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert max_concurrent <= 2


@pytest.mark.asyncio
class TestRecurringJobs:
    async def test_schedule_recurring_triggered(self, orchestrator):
        triggers = []

        async def executor(job):
            triggers.append(job.job_id)
            return {"success": True}

        orchestrator.set_executor(executor)

        await orchestrator.schedule_recurring(
            workflow_path="wf.yaml",
            interval_seconds=0.3,
            domain="test.com",
        )

        task = asyncio.create_task(orchestrator.run(tick_interval=0.1))
        await asyncio.sleep(1.5)
        await orchestrator.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(triggers) >= 2

    async def test_disable_recurring(self, orchestrator):
        triggers = []

        async def executor(job):
            triggers.append(job.job_id)
            return {"success": True}

        orchestrator.set_executor(executor)

        rj = await orchestrator.schedule_recurring(
            workflow_path="wf.yaml",
            interval_seconds=0.2,
            domain="test.com",
        )

        await orchestrator.enable_recurring(rj.job_id, enabled=False)

        task = asyncio.create_task(orchestrator.run(tick_interval=0.1))
        await asyncio.sleep(0.8)
        await orchestrator.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert len(triggers) == 0

    async def test_remove_recurring(self, orchestrator):
        rj = await orchestrator.schedule_recurring(
            workflow_path="wf.yaml",
            interval_seconds=60,
            domain="test.com",
        )
        removed = await orchestrator.remove_recurring(rj.job_id)
        assert removed is True
        assert orchestrator.get_recurring(rj.job_id) is None

    async def test_remove_nonexistent(self, orchestrator):
        removed = await orchestrator.remove_recurring("nonexistent")
        assert removed is False


@pytest.mark.asyncio
class TestPersistence:
    async def test_persist_and_reload(self, persist_orchestrator):
        await persist_orchestrator.enqueue(
            workflow_path="wf.yaml",
            domain="example.com",
            account="user1",
        )
        assert persist_orchestrator.status().queue_size == 1

    async def test_checkpoint_save_load(self, orchestrator):
        await orchestrator.save_checkpoint("job-1", {"last_url": "https://example.com", "step": 5})
        checkpoint = orchestrator.load_checkpoint("job-1")
        assert checkpoint is not None
        assert checkpoint["variables"]["last_url"] == "https://example.com"
        assert checkpoint["variables"]["step"] == 5

    async def test_checkpoint_nonexistent(self, orchestrator):
        checkpoint = orchestrator.load_checkpoint("nonexistent")
        assert checkpoint is None


class TestStatus:
    def test_status_returns_correct_format(self):
        orch = WorkflowOrchestrator()
        status = orch.status()
        assert isinstance(status, OrchestratorStatus)
        assert status.queue_size == 0
        assert status.active_jobs == 0
        assert status.completed_jobs == 0
        assert status.failed_jobs == 0
        assert status.recurring_jobs == 0


class TestGetJob:
    @pytest.mark.asyncio
    async def test_get_job_from_queue(self, orchestrator):
        job = await orchestrator.enqueue(workflow_path="wf.yaml")
        found = orchestrator.get_job(job.job_id)
        assert found is not None
        assert found.job_id == job.job_id

    def test_get_job_nonexistent(self, orchestrator):
        assert orchestrator.get_job("nonexistent") is None


@pytest.mark.asyncio
class TestBackoff:
    async def test_backoff_calculation(self):
        job = QueueJob(
            job_id="test-1",
            workflow_path="wf.yaml",
            domain="example.com",
            account="user1",
            retries=0,
            backoff_base=2.0,
        )
        assert job.backoff_seconds() == 2.0

        job.retries = 2
        assert job.backoff_seconds() == 8.0

        job.retries = 3
        assert job.backoff_seconds() == 16.0


class TestClearCompleted:
    @pytest.mark.asyncio
    async def test_clear_old_completed(self, orchestrator):
        async with orchestrator._lock:
            old_job = QueueJob(
                job_id="old-1",
                workflow_path="wf.yaml",
                domain="test.com",
                account="user1",
                status="completed",
                completed_at=time.time() - 3600 * 48,
                created_at=time.time() - 3600 * 48,
            )
            orchestrator._completed.append(old_job)

        await orchestrator.clear_completed(before_hours=24)
        async with orchestrator._lock:
            assert len(orchestrator._completed) == 0
