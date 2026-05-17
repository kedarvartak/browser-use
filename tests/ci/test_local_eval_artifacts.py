from browser_use.benchmarking.local_eval import (
	BenchmarkTaskArtifact,
	FailureCategory,
	RunStatus,
	build_run_report,
	detect_failure_category,
	load_existing_task_artifact,
	task_artifact_path,
	write_task_artifact,
)


def make_artifact(**overrides) -> BenchmarkTaskArtifact:
	base = {
		'task_name': 'sample-task',
		'task_file': '/tmp/sample-task.yaml',
		'task': 'Solve the task',
		'judge_context': ['Solve the task'],
		'max_steps': 10,
		'status': RunStatus.PASSED,
		'verdict': True,
		'counted_as_pass': True,
		'explanation': 'Completed successfully',
		'failure_category': FailureCategory.SUCCESS,
		'started_at': '2026-05-17T00:00:00+00:00',
		'completed_at': '2026-05-17T00:00:02+00:00',
	}
	base.update(overrides)
	return BenchmarkTaskArtifact(**base)


def test_task_artifact_round_trip(tmp_path):
	artifact = make_artifact()
	artifact_path = write_task_artifact(tmp_path, artifact)

	assert artifact_path == task_artifact_path(tmp_path, artifact.task_name)
	assert artifact_path.exists()

	reloaded = load_existing_task_artifact(tmp_path, artifact.task_name)

	assert reloaded is not None
	assert reloaded.task_name == artifact.task_name
	assert reloaded.counted_as_pass is True
	assert reloaded.artifact_path == str(artifact_path)


def test_build_run_report_tracks_counts_and_resume(tmp_path):
	artifacts = [
		make_artifact(task_name='passed-task'),
		make_artifact(
			task_name='failed-task',
			status=RunStatus.FAILED,
			verdict=False,
			counted_as_pass=False,
			explanation='Task failed with error: page never loaded',
			failure_category=FailureCategory.AGENT_ERROR,
		),
		make_artifact(
			task_name='skipped-task',
			status=RunStatus.SKIPPED,
			verdict=None,
			counted_as_pass=True,
			explanation='Skipped - BROWSER_USE_API_KEY is not set (fork PR or missing secret)',
			failure_category=FailureCategory.SKIPPED_MISSING_AGENT_API_KEY,
			result_source='resume',
		),
	]

	report = build_run_report(
		task_dir='tests/agent_tasks',
		results_dir=tmp_path,
		started_at='2026-05-17T00:00:00+00:00',
		completed_at='2026-05-17T00:10:00+00:00',
		artifacts=artifacts,
		commit_sha='abc123',
	)

	assert report.total_tasks == 3
	assert report.passed_count == 2
	assert report.failed_count == 1
	assert report.skipped_count == 1
	assert report.resumed_count == 1
	assert report.pass_rate == round((1 / 3) * 100, 2)
	assert report.counted_pass_rate == round((2 / 3) * 100, 2)
	assert report.failure_categories == {
		'agent_error': 1,
		'skipped_missing_agent_api_key': 1,
		'success': 1,
	}


def test_detect_failure_category():
	assert (
		detect_failure_category(
			success=False,
			explanation='Skipped - GOOGLE_API_KEY is not set (fork PR or missing secret)',
			status=RunStatus.SKIPPED,
		)
		== FailureCategory.SKIPPED_MISSING_JUDGE_API_KEY
	)
	assert (
		detect_failure_category(
			success=False,
			explanation='Failed to parse subprocess result: bad json',
			status=RunStatus.FAILED,
		)
		== FailureCategory.PARSE_ERROR
	)
	assert (
		detect_failure_category(
			success=False,
			explanation='Judge says the result does not satisfy the criteria',
			final_result='some answer',
			status=RunStatus.FAILED,
		)
		== FailureCategory.JUDGE_FAILURE
	)
