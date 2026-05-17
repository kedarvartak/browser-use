import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
	PASSED = 'passed'
	FAILED = 'failed'
	SKIPPED = 'skipped'


class FailureCategory(StrEnum):
	SUCCESS = 'success'
	SKIPPED_MISSING_AGENT_API_KEY = 'skipped_missing_agent_api_key'
	SKIPPED_MISSING_JUDGE_API_KEY = 'skipped_missing_judge_api_key'
	SKIPPED_OTHER = 'skipped_other'
	NO_OUTPUT = 'no_output'
	JUDGE_FAILURE = 'judge_failure'
	BROWSER_SETUP_ERROR = 'browser_setup_error'
	AGENT_ERROR = 'agent_error'
	SUBPROCESS_ERROR = 'subprocess_error'
	PARSE_ERROR = 'parse_error'
	STARTUP_ERROR = 'startup_error'
	UNKNOWN = 'unknown'


class BenchmarkTaskArtifact(BaseModel):
	schema_version: int = 1
	benchmark_mode: str = 'local-dev'
	task_name: str
	task_file: str
	task: str
	judge_context: list[str] = Field(default_factory=list)
	max_steps: int
	status: RunStatus
	verdict: bool | None = None
	counted_as_pass: bool = False
	explanation: str
	failure_category: FailureCategory
	skip_reason: str | None = None
	final_result: str = ''
	total_steps: int = 0
	last_action_type: str | None = None
	duration_seconds: float | None = None
	urls: list[str] = Field(default_factory=list)
	errors: list[str] = Field(default_factory=list)
	debug_info: str | None = None
	model_name: str | None = None
	judge_model_name: str | None = None
	commit_sha: str | None = None
	started_at: str
	completed_at: str
	artifact_path: str | None = None
	result_source: str = 'fresh'


class BenchmarkRunTaskSummary(BaseModel):
	task_name: str
	task_file: str
	status: RunStatus
	counted_as_pass: bool
	failure_category: FailureCategory
	result_source: str
	artifact_path: str | None = None


class BenchmarkRunReport(BaseModel):
	schema_version: int = 1
	benchmark_mode: str = 'local-dev'
	task_dir: str
	results_dir: str
	commit_sha: str | None = None
	started_at: str
	completed_at: str
	total_tasks: int
	passed_count: int
	failed_count: int
	skipped_count: int
	resumed_count: int
	pass_rate: float
	counted_pass_rate: float
	failure_categories: dict[str, int]
	tasks: list[BenchmarkRunTaskSummary]


def utc_now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def slugify_task_name(task_name: str) -> str:
	slug = re.sub(r'[^a-zA-Z0-9]+', '-', task_name).strip('-').lower()
	return slug or 'task'


def task_artifact_path(results_dir: str | Path, task_name: str) -> Path:
	return Path(results_dir) / 'tasks' / f'{slugify_task_name(task_name)}.json'


def detect_commit_sha() -> str | None:
	if sha := os.getenv('GITHUB_SHA'):
		return sha
	try:
		result = subprocess.run(
			['git', 'rev-parse', 'HEAD'],
			check=True,
			capture_output=True,
			text=True,
		)
		return result.stdout.strip() or None
	except (FileNotFoundError, subprocess.SubprocessError):
		return None


def detect_failure_category(
	*,
	success: bool,
	explanation: str,
	final_result: str = '',
	status: RunStatus,
) -> FailureCategory:
	if status == RunStatus.PASSED and success:
		return FailureCategory.SUCCESS

	explanation_lower = explanation.lower()
	if status == RunStatus.SKIPPED:
		if 'browser_use_api_key' in explanation_lower:
			return FailureCategory.SKIPPED_MISSING_AGENT_API_KEY
		if 'google_api_key' in explanation_lower:
			return FailureCategory.SKIPPED_MISSING_JUDGE_API_KEY
		return FailureCategory.SKIPPED_OTHER

	if not final_result.strip():
		if 'browser test failed' in explanation_lower or 'browser session' in explanation_lower:
			return FailureCategory.BROWSER_SETUP_ERROR
		if 'subprocess failed' in explanation_lower:
			return FailureCategory.SUBPROCESS_ERROR
		if 'parse subprocess result' in explanation_lower or 'no json found' in explanation_lower:
			return FailureCategory.PARSE_ERROR
		if 'failed to start subprocess' in explanation_lower or 'critical subprocess error' in explanation_lower:
			return FailureCategory.STARTUP_ERROR
		if 'agent.run() failed' in explanation_lower or 'task failed with error' in explanation_lower:
			return FailureCategory.AGENT_ERROR
		return FailureCategory.NO_OUTPUT

	if 'subprocess failed' in explanation_lower:
		return FailureCategory.SUBPROCESS_ERROR
	if 'parse subprocess result' in explanation_lower or 'no json found' in explanation_lower:
		return FailureCategory.PARSE_ERROR
	if 'browser test failed' in explanation_lower or 'browser session' in explanation_lower:
		return FailureCategory.BROWSER_SETUP_ERROR
	if 'agent.run() failed' in explanation_lower or 'task failed with error' in explanation_lower:
		return FailureCategory.AGENT_ERROR
	if not success:
		return FailureCategory.JUDGE_FAILURE
	return FailureCategory.UNKNOWN


def load_existing_task_artifact(results_dir: str | Path, task_name: str) -> BenchmarkTaskArtifact | None:
	artifact_file = task_artifact_path(results_dir, task_name)
	if not artifact_file.exists():
		return None
	try:
		return BenchmarkTaskArtifact.model_validate_json(artifact_file.read_text())
	except (OSError, ValueError):
		return None


def write_task_artifact(results_dir: str | Path, artifact: BenchmarkTaskArtifact) -> Path:
	artifact_file = task_artifact_path(results_dir, artifact.task_name)
	artifact_file.parent.mkdir(parents=True, exist_ok=True)
	artifact_with_path = artifact.model_copy(update={'artifact_path': str(artifact_file)})
	artifact_file.write_text(json.dumps(artifact_with_path.model_dump(mode='json'), indent=2) + '\n')
	return artifact_file


def build_run_report(
	*,
	task_dir: str | Path,
	results_dir: str | Path,
	started_at: str,
	completed_at: str,
	artifacts: list[BenchmarkTaskArtifact],
	benchmark_mode: str = 'local-dev',
	commit_sha: str | None = None,
) -> BenchmarkRunReport:
	total_tasks = len(artifacts)
	passed_count = sum(1 for artifact in artifacts if artifact.counted_as_pass)
	failed_count = sum(1 for artifact in artifacts if artifact.status == RunStatus.FAILED)
	skipped_count = sum(1 for artifact in artifacts if artifact.status == RunStatus.SKIPPED)
	resumed_count = sum(1 for artifact in artifacts if artifact.result_source == 'resume')
	failure_categories = dict(sorted(Counter(artifact.failure_category.value for artifact in artifacts).items()))
	tasks = [
		BenchmarkRunTaskSummary(
			task_name=artifact.task_name,
			task_file=artifact.task_file,
			status=artifact.status,
			counted_as_pass=artifact.counted_as_pass,
			failure_category=artifact.failure_category,
			result_source=artifact.result_source,
			artifact_path=artifact.artifact_path,
		)
		for artifact in artifacts
	]
	denominator = total_tasks or 1
	return BenchmarkRunReport(
		benchmark_mode=benchmark_mode,
		task_dir=str(task_dir),
		results_dir=str(results_dir),
		commit_sha=commit_sha,
		started_at=started_at,
		completed_at=completed_at,
		total_tasks=total_tasks,
		passed_count=passed_count,
		failed_count=failed_count,
		skipped_count=skipped_count,
		resumed_count=resumed_count,
		pass_rate=round((sum(1 for artifact in artifacts if artifact.verdict is True) / denominator) * 100, 2),
		counted_pass_rate=round((passed_count / denominator) * 100, 2),
		failure_categories=failure_categories,
		tasks=tasks,
	)


def write_run_report(results_dir: str | Path, report: BenchmarkRunReport) -> Path:
	results_path = Path(results_dir)
	results_path.mkdir(parents=True, exist_ok=True)
	report_file = results_path / 'summary.json'
	report_file.write_text(json.dumps(report.model_dump(mode='json'), indent=2) + '\n')
	return report_file
