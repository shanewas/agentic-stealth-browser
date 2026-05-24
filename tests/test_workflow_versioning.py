"""Tests for workflow versioning and diff in v1.2.0."""

from workflows.recorder import WorkflowRecorder
from workflows.schema import (
    SCHEMA_VERSION,
    Workflow,
    WorkflowStep,
    workflow_diff,
    workflow_to_dict,
    load_workflow,
)


class TestWorkflowVersion:
    def test_default_version(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        assert workflow.version == SCHEMA_VERSION

    def test_load_workflow_preserves_version(self):
        data = {
            "name": "test",
            "version": "2.0.0",
            "steps": [{"type": "navigate", "url": "https://example.com"}],
        }
        workflow = load_workflow(data)
        assert workflow.version == "2.0.0"

    def test_workflow_to_dict_includes_version(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
            version="1.2.0",
        )
        d = workflow_to_dict(workflow)
        assert d["version"] == "1.2.0"

    def test_workflow_to_dict_includes_metadata(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
            metadata={"recorded_at": "2024-01-01T00:00:00Z", "changelog": []},
        )
        d = workflow_to_dict(workflow)
        assert "metadata" in d
        assert d["metadata"]["recorded_at"] == "2024-01-01T00:00:00Z"


class TestWorkflowDiff:
    def test_diff_name_change(self):
        old = Workflow(
            name="old",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        new = Workflow(
            name="new",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        diff = workflow_diff(old, new)
        assert diff["name_changed"] is True

    def test_diff_description_change(self):
        old = Workflow(
            name="test",
            steps=[],
            description="Old description",
        )
        new = Workflow(
            name="test",
            steps=[],
            description="New description",
        )
        diff = workflow_diff(old, new)
        assert diff["description_changed"] is True

    def test_diff_step_added(self):
        old = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        new = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        diff = workflow_diff(old, new)
        assert diff["steps_added"] == 1
        assert 1 in diff["added_step_indices"]

    def test_diff_step_removed(self):
        old = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        new = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        diff = workflow_diff(old, new)
        assert diff["steps_removed"] == 1
        assert 1 in diff["removed_step_indices"]

    def test_diff_type_changed(self):
        old = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        new = Workflow(
            name="test", steps=[WorkflowStep(type="click", params={"selector": "#btn"})]
        )
        diff = workflow_diff(old, new)
        assert diff["steps_modified"] == 1
        assert 0 in diff["modified_step_indices"]

    def test_diff_params_changed(self):
        old = Workflow(
            name="test",
            steps=[WorkflowStep(type="navigate", params={"url": "https://old.com"})],
        )
        new = Workflow(
            name="test",
            steps=[WorkflowStep(type="navigate", params={"url": "https://new.com"})],
        )
        diff = workflow_diff(old, new)
        assert diff["steps_modified"] == 1
        assert diff["details"][0]["change"] == "params_modified"

    def test_diff_no_change(self):
        old = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        new = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        diff = workflow_diff(old, new)
        assert diff["steps_added"] == 0
        assert diff["steps_removed"] == 0
        assert diff["steps_modified"] == 0

    def test_diff_version_tracking(self):
        old = Workflow(name="test", steps=[], version="1.0.0")
        new = Workflow(name="test", steps=[], version="1.2.0")
        diff = workflow_diff(old, new)
        assert diff["version_old"] == "1.0.0"
        assert diff["version_new"] == "1.2.0"


class TestRecorderChangelog:
    def test_to_workflow_includes_metadata(self):
        recorder = WorkflowRecorder()
        recorder.on_cdp_event(
            {
                "method": "Page.frameNavigated",
                "params": {"frame": {"url": "https://example.com", "id": "main"}},
            }
        )
        recorder.on_cdp_event(
            {
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "click",
                    "button": "left",
                    "x": 100,
                    "y": 200,
                    "tagName": "button",
                    "id": "btn",
                    "className": "btn",
                    "textContent": "Go",
                    "attributes": {},
                },
            }
        )
        workflow = recorder.to_workflow(name="test-changelog")
        assert workflow.metadata is not None
        assert "changelog" in workflow.metadata
        assert len(workflow.metadata["changelog"]) == 1
        assert workflow.metadata["changelog"][0]["action"] == "recorded"
        assert "average_confidence" in workflow.metadata
        assert "low_confidence_steps" in workflow.metadata

    def test_append_changelog(self):
        recorder = WorkflowRecorder()
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
            metadata={"changelog": []},
        )
        updated = recorder.append_changelog(workflow, "edited", "Added a verify step")
        assert len(updated.metadata["changelog"]) == 1
        assert updated.metadata["changelog"][0]["action"] == "edited"
        assert "saved_at" in updated.metadata

    def test_append_changelog_no_existing_metadata(self):
        recorder = WorkflowRecorder()
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        updated = recorder.append_changelog(workflow, "saved", "Initial save")
        assert updated.metadata is not None
        assert len(updated.metadata["changelog"]) == 1
