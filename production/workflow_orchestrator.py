import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class QueueJob:
    job_id: str
    workflow_path: str
    domain: str
    account: str
    variables: Dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    created_at: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0
    max_retries: int = 3
    backoff_base: float = 2.0
    last_error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    priority: int = 0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def backoff_seconds(self) -> float:
        return self.backoff_base * (2 ** self.retries)


@dataclass
class RecurringJob:
    job_id: str
    workflow_path: str
    domain: str
    account: str
    interval_seconds: float
    variables: Dict[str, Any] = field(default_factory=dict)
    next_run_at: float = 0.0
    max_concurrent: int = 1
    created_at: float = 0.0
    enabled: bool = True
    last_run_at: Optional[float] = None
    last_result: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.next_run_at == 0.0:
            self.next_run_at = self.created_at


@dataclass
class OrchestratorStatus:
    queue_size: int
    active_jobs: int
    completed_jobs: int
    failed_jobs: int
    recurring_jobs: int
    domain_slots: Dict[str, int]


class WorkflowOrchestrator:

    def __init__(
        self,
        max_concurrent_total: int = 5,
        domain_concurrency: Optional[Dict[str, int]] = None,
        persistence_path: Optional[str] = None,
    ):
        self._queue: List[QueueJob] = []
        self._active: Dict[str, QueueJob] = {}
        self._completed: List[QueueJob] = []
        self._failed: List[QueueJob] = []
        self._recurring: Dict[str, RecurringJob] = {}
        self._domain_slots: Dict[str, int] = {}
        self._domain_active: Dict[str, int] = {}
        self._max_concurrent_total = max_concurrent_total
        self._domain_concurrency = domain_concurrency or {"linkedin.com": 1, "default": 3}
        self._persistence_path = persistence_path
        self._lock = asyncio.Lock()
        self._running = False
        self._executor: Optional[Callable] = None
        self._job_counter = 0

        if self._persistence_path:
            self._load_state()

    def _next_job_id(self) -> str:
        self._job_counter += 1
        return f"job-{self._job_counter}-{int(time.time())}"

    @staticmethod
    def extract_domain(url_or_path: str) -> str:
        if "://" in url_or_path:
            parsed = urlparse(url_or_path)
            return parsed.netloc or "unknown"
        return "workflow"

    # ---- queue management ----

    async def enqueue(
        self,
        workflow_path: str,
        domain: Optional[str] = None,
        account: str = "default",
        variables: Optional[Dict[str, Any]] = None,
        priority: int = 0,
        max_retries: int = 3,
    ) -> QueueJob:
        job = QueueJob(
            job_id=self._next_job_id(),
            workflow_path=workflow_path,
            domain=domain or self.extract_domain(workflow_path),
            account=account,
            variables=variables or {},
            priority=priority,
            max_retries=max_retries,
        )
        async with self._lock:
            self._queue.append(job)
            self._queue.sort(key=lambda j: j.priority, reverse=True)
        await self._persist()
        return job

    async def enqueue_batch(
        self,
        jobs: List[Dict[str, Any]],
    ) -> List[QueueJob]:
        created: List[QueueJob] = []
        for spec in jobs:
            job = await self.enqueue(
                workflow_path=spec["workflow_path"],
                domain=spec.get("domain"),
                account=spec.get("account", "default"),
                variables=spec.get("variables"),
                priority=spec.get("priority", 0),
                max_retries=spec.get("max_retries", 3),
            )
            created.append(job)
        return created

    async def dequeue(self, job_id: Optional[str] = None) -> Optional[QueueJob]:
        async with self._lock:
            if job_id:
                for i, job in enumerate(self._queue):
                    if job.job_id == job_id:
                        return self._queue.pop(i)
                return None
            if not self._queue:
                return None
            return self._queue.pop(0)

    # ---- concurrency management ----

    def _acquire_slot(self, domain: str) -> bool:
        limit = self._domain_concurrency.get(domain, self._domain_concurrency.get("default", 3))
        current = self._domain_active.get(domain, 0)
        if current >= limit:
            return False
        self._domain_active[domain] = current + 1
        return True

    def _release_slot(self, domain: str):
        current = self._domain_active.get(domain, 0)
        if current > 0:
            self._domain_active[domain] = current - 1

    def _can_run(self, domain: str) -> bool:
        total_active = len(self._active)
        if total_active >= self._max_concurrent_total:
            return False
        limit = self._domain_concurrency.get(domain, self._domain_concurrency.get("default", 3))
        domain_active = self._domain_active.get(domain, 0)
        return domain_active < limit

    # ---- scheduled / recurring execution ----

    async def schedule_recurring(
        self,
        workflow_path: str,
        interval_seconds: float,
        domain: Optional[str] = None,
        account: str = "default",
        variables: Optional[Dict[str, Any]] = None,
        max_concurrent: int = 1,
    ) -> RecurringJob:
        job = RecurringJob(
            job_id=self._next_job_id(),
            workflow_path=workflow_path,
            domain=domain or self.extract_domain(workflow_path),
            account=account,
            interval_seconds=interval_seconds,
            variables=variables or {},
            max_concurrent=max_concurrent,
        )
        async with self._lock:
            self._recurring[job.job_id] = job
        await self._persist()
        return job

    async def remove_recurring(self, job_id: str) -> bool:
        async with self._lock:
            if job_id in self._recurring:
                del self._recurring[job_id]
                await self._persist()
                return True
        return False

    async def enable_recurring(self, job_id: str, enabled: bool = True):
        async with self._lock:
            if job_id in self._recurring:
                self._recurring[job_id].enabled = enabled
                await self._persist()

    # ---- checkpoint persistence ----

    def _checkpoint_path(self, job_id: str) -> str:
        base = self._persistence_path or "checkpoints/orchestrator"
        Path(base).mkdir(parents=True, exist_ok=True)
        return f"{base}/job_{job_id}.json"

    async def save_checkpoint(self, job_id: str, variables: Dict[str, Any]):
        path = self._checkpoint_path(job_id)
        data = {
            "job_id": job_id,
            "saved_at": time.time(),
            "variables": variables,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_checkpoint(self, job_id: str) -> Optional[Dict[str, Any]]:
        path = self._checkpoint_path(job_id)
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    # ---- persistence ----

    async def _persist(self):
        if not self._persistence_path:
            return
        Path(self._persistence_path).parent.mkdir(parents=True, exist_ok=True)
        state = {
            "saved_at": time.time(),
            "queue": [
                {
                    "job_id": j.job_id, "workflow_path": j.workflow_path,
                    "domain": j.domain, "account": j.account,
                    "variables": j.variables, "status": j.status,
                    "created_at": j.created_at, "retries": j.retries,
                    "max_retries": j.max_retries, "priority": j.priority,
                    "backoff_base": j.backoff_base, "last_error": j.last_error,
                }
                for j in self._queue
            ],
            "completed_ids": [j.job_id for j in self._completed[-100:]],
            "failed_ids": [j.job_id for j in self._failed[-100:]],
            "recurring": {
                jid: {
                    "job_id": rj.job_id, "workflow_path": rj.workflow_path,
                    "domain": rj.domain, "account": rj.account,
                    "interval_seconds": rj.interval_seconds,
                    "variables": rj.variables, "max_concurrent": rj.max_concurrent,
                    "next_run_at": rj.next_run_at, "enabled": rj.enabled,
                    "last_run_at": rj.last_run_at,
                }
                for jid, rj in self._recurring.items()
            },
        }
        with open(self._persistence_path, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        if not self._persistence_path:
            return
        try:
            with open(self._persistence_path, "r") as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        for item in state.get("queue", []):
            job = QueueJob(
                job_id=item["job_id"],
                workflow_path=item["workflow_path"],
                domain=item.get("domain", "unknown"),
                account=item.get("account", "default"),
                variables=item.get("variables", {}),
                status=item.get("status", "queued"),
                created_at=item.get("created_at", time.time()),
                retries=item.get("retries", 0),
                max_retries=item.get("max_retries", 3),
                priority=item.get("priority", 0),
                backoff_base=item.get("backoff_base", 2.0),
                last_error=item.get("last_error"),
            )
            self._queue.append(job)

        for jid, data in state.get("recurring", {}).items():
            rj = RecurringJob(
                job_id=data["job_id"],
                workflow_path=data["workflow_path"],
                domain=data.get("domain", "unknown"),
                account=data.get("account", "default"),
                interval_seconds=data["interval_seconds"],
                variables=data.get("variables", {}),
                max_concurrent=data.get("max_concurrent", 1),
                next_run_at=data.get("next_run_at", time.time()),
                enabled=data.get("enabled", True),
                last_run_at=data.get("last_run_at"),
            )
            self._recurring[jid] = rj

        self._job_counter = len(self._queue) + len(self._recurring)

    # ---- execution ----

    def set_executor(self, executor: Callable):
        self._executor = executor

    async def run(self, tick_interval: float = 1.0):
        self._running = True
        while self._running:
            await self._tick_recurring()
            await self._tick_queue()
            await asyncio.sleep(tick_interval)

    async def stop(self):
        self._running = False
        await self._persist()

    async def _tick_recurring(self):
        now = time.time()
        async with self._lock:
            for rj in list(self._recurring.values()):
                if not rj.enabled:
                    continue
                if now < rj.next_run_at:
                    continue
                rj.next_run_at = now + rj.interval_seconds
                rj.last_run_at = now

                job = QueueJob(
                    job_id=f"{rj.job_id}-rec-{int(now)}",
                    workflow_path=rj.workflow_path,
                    domain=rj.domain,
                    account=rj.account,
                    variables=dict(rj.variables),
                    status="queued",
                    created_at=now,
                )
                self._queue.append(job)
                self._queue.sort(key=lambda j: j.priority, reverse=True)

    async def _tick_queue(self):
        async with self._lock:
            for job in list(self._queue):
                if not self._can_run(job.domain):
                    continue
                if self._acquire_slot(job.domain):
                    self._queue.remove(job)
                    job.status = "active"
                    job.started_at = time.time()
                    self._active[job.job_id] = job
                    asyncio.create_task(self._execute_job(job))

    async def _execute_job(self, job: QueueJob):
        try:
            if self._executor:
                result = await self._executor(job)
            else:
                result = {"success": False, "error": "No executor set"}

            job.result = result
            job.completed_at = time.time()

            if result.get("success"):
                job.status = "completed"
                async with self._lock:
                    self._completed.append(job)
            else:
                job.last_error = str(result.get("error", "Unknown error"))
                if job.retries < job.max_retries:
                    job.retries += 1
                    job.status = "queued"
                    delay = job.backoff_seconds()
                    job.created_at = time.time()
                    async with self._lock:
                        self._queue.append(job)
                        self._queue.sort(key=lambda j: j.priority, reverse=True)
                        self._active.pop(job.job_id, None)
                        self._release_slot(job.domain)
                    await asyncio.sleep(delay)
                    return
                else:
                    job.status = "failed"
                    async with self._lock:
                        self._failed.append(job)
        except Exception as e:
            job.last_error = str(e)
            job.status = "failed"
            async with self._lock:
                self._failed.append(job)
        finally:
            if job.status in ("completed", "failed"):
                async with self._lock:
                    self._active.pop(job.job_id, None)
                    self._release_slot(job.domain)
            await self._persist()

    def status(self) -> OrchestratorStatus:
        return OrchestratorStatus(
            queue_size=len(self._queue),
            active_jobs=len(self._active),
            completed_jobs=len(self._completed),
            failed_jobs=len(self._failed),
            recurring_jobs=len(self._recurring),
            domain_slots=dict(self._domain_active),
        )

    def get_job(self, job_id: str) -> Optional[QueueJob]:
        for collection in [self._active, dict((j.job_id, j) for j in self._queue),
                           dict((j.job_id, j) for j in self._completed),
                           dict((j.job_id, j) for j in self._failed)]:
            if isinstance(collection, dict) and job_id in collection:
                return collection[job_id]
        return None

    def get_recurring(self, job_id: str) -> Optional[RecurringJob]:
        return self._recurring.get(job_id)

    async def clear_completed(self, before_hours: float = 24.0):
        cutoff = time.time() - (before_hours * 3600)
        async with self._lock:
            self._completed = [
                j for j in self._completed
                if j.completed_at and j.completed_at >= cutoff
            ]
            self._failed = [
                j for j in self._failed
                if j.completed_at and j.completed_at >= cutoff
            ]
        await self._persist()
