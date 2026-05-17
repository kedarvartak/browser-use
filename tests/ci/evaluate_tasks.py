"""Run local benchmark-style agent tasks and persist structured artifacts."""

import argparse
import asyncio
import glob
import json
import logging
import os
import sys
import warnings
from pathlib import Path

import anyio
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()
from browser_use import Agent, AgentHistoryList, BrowserProfile, BrowserSession, ChatBrowserUse
from browser_use.benchmarking import (
	BenchmarkTaskArtifact,
	FailureCategory,
	RunStatus,
	build_run_report,
	detect_commit_sha,
	detect_failure_category,
	load_existing_task_artifact,
	utc_now_iso,
	write_run_report,
	write_task_artifact,
)
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.messages import UserMessage

MAX_PARALLEL = 10
DEFAULT_RESULTS_DIR = Path('tmp/evaluate_tasks')


def get_default_task_dir() -> str:
	return os.path.join(os.path.dirname(__file__), '../agent_tasks')


def discover_task_files(task_dir: str) -> list[str]:
	return sorted(glob.glob(os.path.join(task_dir, '*.yaml')))


class JudgeResponse(BaseModel):
	success: bool
	explanation: str


def load_task_definition(task_file: str) -> tuple[dict, str, list[str], int]:
	content = Path(task_file).read_text()
	task_data = yaml.safe_load(content)
	task = task_data['task']
	judge_context = task_data.get('judge_context', ['The agent must solve the task'])
	max_steps = task_data.get('max_steps', 15)
	return task_data, task, judge_context, max_steps


def build_skip_artifact(
	*,
	task_file: str,
	task: str,
	judge_context: list[str],
	max_steps: int,
	explanation: str,
	started_at: str,
	completed_at: str,
	model_name: str | None = None,
	judge_model_name: str | None = None,
) -> BenchmarkTaskArtifact:
	return BenchmarkTaskArtifact(
		task_name=os.path.splitext(os.path.basename(task_file))[0],
		task_file=os.path.abspath(task_file),
		task=task,
		judge_context=judge_context,
		max_steps=max_steps,
		status=RunStatus.SKIPPED,
		verdict=None,
		counted_as_pass=True,
		explanation=explanation,
		failure_category=detect_failure_category(
			success=False,
			explanation=explanation,
			status=RunStatus.SKIPPED,
		),
		skip_reason=explanation,
		model_name=model_name,
		judge_model_name=judge_model_name,
		commit_sha=detect_commit_sha(),
		started_at=started_at,
		completed_at=completed_at,
	)


async def run_single_task(task_file: str, results_dir: str, resume: bool = True) -> BenchmarkTaskArtifact:
	"""Run a single task in the current process (called by subprocess)"""
	task_name = os.path.splitext(os.path.basename(task_file))[0]
	existing_artifact = load_existing_task_artifact(results_dir, task_name) if resume else None
	if existing_artifact:
		return existing_artifact.model_copy(update={'result_source': 'resume'})

	started_at = anyio.current_time()
	started_at_iso = utc_now_iso()
	session: BrowserSession | None = None
	task = ''
	judge_context: list[str] = []
	max_steps = 15
	model_name = 'ChatBrowserUse'
	judge_model_name = 'gemini-flash-lite-latest'
	try:
		print(f'[DEBUG] Starting task: {os.path.basename(task_file)}', file=sys.stderr)

		# Suppress all logging in subprocess to avoid interfering with JSON output
		logging.getLogger().setLevel(logging.CRITICAL)
		for logger_name in ['browser_use', 'telemetry', 'message_manager']:
			logging.getLogger(logger_name).setLevel(logging.CRITICAL)
		warnings.filterwarnings('ignore')

		print('[DEBUG] Loading task file...', file=sys.stderr)
		_, task, judge_context, max_steps = load_task_definition(task_file)

		print(f'[DEBUG] Task: {task[:100]}...', file=sys.stderr)
		print(f'[DEBUG] Max steps: {max_steps}', file=sys.stderr)
		api_key = os.getenv('BROWSER_USE_API_KEY')
		if not api_key:
			print('[SKIP] BROWSER_USE_API_KEY is not set - skipping task evaluation', file=sys.stderr)
			artifact = build_skip_artifact(
				task_file=task_file,
				task=task,
				judge_context=judge_context,
				max_steps=max_steps,
				explanation='Skipped - BROWSER_USE_API_KEY is not set (fork PR or missing secret)',
				started_at=started_at_iso,
				completed_at=utc_now_iso(),
				model_name=model_name,
				judge_model_name=judge_model_name,
			)
			artifact = artifact.model_copy(update={'artifact_path': str(write_task_artifact(results_dir, artifact))})
			return artifact

		agent_llm = ChatBrowserUse(api_key=api_key)
		model_name = getattr(agent_llm, 'model_name', None) or getattr(agent_llm, 'model', None) or 'ChatBrowserUse'

		# Check if Google API key is available for judge LLM
		google_api_key = os.getenv('GOOGLE_API_KEY')
		if not google_api_key:
			print('[SKIP] GOOGLE_API_KEY is not set - skipping task evaluation', file=sys.stderr)
			artifact = build_skip_artifact(
				task_file=task_file,
				task=task,
				judge_context=judge_context,
				max_steps=max_steps,
				explanation='Skipped - GOOGLE_API_KEY is not set (fork PR or missing secret)',
				started_at=started_at_iso,
				completed_at=utc_now_iso(),
				model_name=model_name,
				judge_model_name=judge_model_name,
			)
			artifact = artifact.model_copy(update={'artifact_path': str(write_task_artifact(results_dir, artifact))})
			return artifact

		judge_llm = ChatGoogle(model='gemini-flash-lite-latest')
		judge_model_name = getattr(judge_llm, 'model_name', None) or getattr(judge_llm, 'model', None) or judge_model_name
		print('[DEBUG] LLMs initialized', file=sys.stderr)

		# Each subprocess gets its own profile and session
		print('[DEBUG] Creating browser session...', file=sys.stderr)
		profile = BrowserProfile(
			headless=True,
			user_data_dir=None,
			chromium_sandbox=False,  # Disable sandbox for CI environment (GitHub Actions)
		)
		session = BrowserSession(browser_profile=profile)
		print('[DEBUG] Browser session created', file=sys.stderr)

		# Test if browser is working
		try:
			await session.start()
			from browser_use.browser.events import NavigateToUrlEvent

			event = session.event_bus.dispatch(NavigateToUrlEvent(url='https://httpbin.org/get', new_tab=True))
			await event
			print('[DEBUG] Browser test: navigation successful', file=sys.stderr)
			title = await session.get_current_page_title()
			print(f"[DEBUG] Browser test: got title '{title}'", file=sys.stderr)
		except Exception as browser_error:
			print(f'[DEBUG] Browser test failed: {str(browser_error)}', file=sys.stderr)
			print(
				f'[DEBUG] Browser error type: {type(browser_error).__name__}',
				file=sys.stderr,
			)

		print('[DEBUG] Starting agent execution...', file=sys.stderr)
		agent = Agent(task=task, llm=agent_llm, browser_session=session)

		try:
			history: AgentHistoryList = await agent.run(max_steps=max_steps)
			print('[DEBUG] Agent.run() returned successfully', file=sys.stderr)
		except Exception as agent_error:
			print(
				f'[DEBUG] Agent.run() failed with error: {str(agent_error)}',
				file=sys.stderr,
			)
			print(f'[DEBUG] Error type: {type(agent_error).__name__}', file=sys.stderr)
			# Re-raise to be caught by outer try-catch
			raise agent_error

		agent_output = history.final_result() or ''
		print('[DEBUG] Agent execution completed', file=sys.stderr)

		# Test if LLM is working by making a simple call
		try:
			response = await agent_llm.ainvoke([UserMessage(content="Say 'test'")])
			print(
				f'[DEBUG] LLM test call successful: {response.completion[:50]}',
				file=sys.stderr,
			)
		except Exception as llm_error:
			print(f'[DEBUG] LLM test call failed: {str(llm_error)}', file=sys.stderr)

		# Debug: capture more details about the agent execution
		total_steps = len(history.history) if hasattr(history, 'history') else 0
		last_action = history.history[-1] if hasattr(history, 'history') and history.history else None
		debug_info = f'Steps: {total_steps}, Final result length: {len(agent_output)}'
		if last_action:
			debug_info += f', Last action: {type(last_action).__name__}'

		# Log to stderr so it shows up in GitHub Actions (won't interfere with JSON output to stdout)
		print(f'[DEBUG] Task {os.path.basename(task_file)}: {debug_info}', file=sys.stderr)
		if agent_output:
			print(
				f'[DEBUG] Agent output preview: {agent_output[:200]}...',
				file=sys.stderr,
			)
		else:
			print('[DEBUG] Agent produced no output!', file=sys.stderr)

		criteria = '\n- '.join(judge_context)
		judge_prompt = f"""
You are a evaluator of a browser agent task inside a ci/cd pipeline. Here was the agent's task:
{task}

Here is the agent's output:
{agent_output if agent_output else '[No output provided]'}

Debug info: {debug_info}

Criteria for success:
- {criteria}

Reply in JSON with keys: success (true/false), explanation (string).
If the agent provided no output, explain what might have gone wrong.
"""
		response = await judge_llm.ainvoke([UserMessage(content=judge_prompt)], output_format=JudgeResponse)
		judge_response = response.completion

		status = RunStatus.PASSED if judge_response.success else RunStatus.FAILED
		duration_seconds = round(anyio.current_time() - started_at, 3)
		artifact = BenchmarkTaskArtifact(
			task_name=task_name,
			task_file=os.path.abspath(task_file),
			task=task,
			judge_context=judge_context,
			max_steps=max_steps,
			status=status,
			verdict=judge_response.success,
			counted_as_pass=judge_response.success,
			explanation=judge_response.explanation,
			failure_category=detect_failure_category(
				success=judge_response.success,
				explanation=judge_response.explanation,
				final_result=agent_output,
				status=status,
			),
			final_result=agent_output,
			total_steps=total_steps,
			last_action_type=type(last_action).__name__ if last_action else None,
			duration_seconds=duration_seconds,
			urls=history.urls(),
			errors=[error for error in history.errors() if error],
			debug_info=debug_info,
			model_name=model_name,
			judge_model_name=judge_model_name,
			commit_sha=detect_commit_sha(),
			started_at=started_at_iso,
			completed_at=utc_now_iso(),
		)

		# Clean up session before returning
		await session.kill()
		session = None
		artifact = artifact.model_copy(update={'artifact_path': str(write_task_artifact(results_dir, artifact))})

		return artifact

	except Exception as e:
		# Ensure session cleanup even on error
		try:
			if session is not None:
				await session.kill()
		except Exception:
			pass

		duration_seconds = round(anyio.current_time() - started_at, 3)
		explanation = f'Task failed with error: {str(e)}'
		artifact = BenchmarkTaskArtifact(
			task_name=task_name,
			task_file=os.path.abspath(task_file),
			task=task,
			judge_context=judge_context,
			max_steps=max_steps,
			status=RunStatus.FAILED,
			verdict=False,
			counted_as_pass=False,
			explanation=explanation,
			failure_category=detect_failure_category(
				success=False,
				explanation=explanation,
				status=RunStatus.FAILED,
			),
			duration_seconds=duration_seconds,
			model_name=model_name,
			judge_model_name=judge_model_name,
			commit_sha=detect_commit_sha(),
			started_at=started_at_iso,
			completed_at=utc_now_iso(),
		)
		artifact = artifact.model_copy(update={'artifact_path': str(write_task_artifact(results_dir, artifact))})
		return artifact


async def run_task_subprocess(task_file: str, semaphore: asyncio.Semaphore, results_dir: str, resume: bool) -> BenchmarkTaskArtifact:
	"""Run a task in a separate subprocess"""
	async with semaphore:
		task_name = os.path.splitext(os.path.basename(task_file))[0]
		existing_artifact = load_existing_task_artifact(results_dir, task_name) if resume else None
		if existing_artifact:
			print(f'[PARENT] Reusing artifact for {os.path.basename(task_file)}')
			return existing_artifact.model_copy(update={'result_source': 'resume'})

		try:
			# Set environment to reduce noise in subprocess
			env = os.environ.copy()
			env['PYTHONPATH'] = os.pathsep.join(sys.path)

			proc = await asyncio.create_subprocess_exec(
				sys.executable,
				__file__,
				'--task',
				task_file,
				'--results-dir',
				results_dir,
				'--no-resume',
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=env,
			)
			stdout, stderr = await proc.communicate()

			if proc.returncode == 0:
				try:
					# Parse JSON result from subprocess
					stdout_text = stdout.decode().strip()
					stderr_text = stderr.decode().strip()

					# Display subprocess debug logs
					if stderr_text:
						print(f'[SUBPROCESS {os.path.basename(task_file)}] Debug output:')
						for line in stderr_text.split('\n'):
							if line.strip():
								print(f'  {line}')

					# Find the JSON line (should be the last line that starts with {)
					lines = stdout_text.split('\n')
					json_line = None
					for line in reversed(lines):
						line = line.strip()
						if line.startswith('{') and line.endswith('}'):
							json_line = line
							break

					if json_line:
						result = BenchmarkTaskArtifact.model_validate_json(json_line)
						print(f'[PARENT] Task {os.path.basename(task_file)} completed: {result.counted_as_pass}')
					else:
						raise ValueError(f'No JSON found in output: {stdout_text}')

				except (json.JSONDecodeError, ValueError) as e:
					task_data, task, judge_context, max_steps = load_task_definition(task_file)
					_ = task_data
					result = BenchmarkTaskArtifact(
						task_name=task_name,
						task_file=os.path.abspath(task_file),
						task=task,
						judge_context=judge_context,
						max_steps=max_steps,
						status=RunStatus.FAILED,
						verdict=False,
						counted_as_pass=False,
						explanation=f'Failed to parse subprocess result: {str(e)[:100]}',
						failure_category=FailureCategory.PARSE_ERROR,
						commit_sha=detect_commit_sha(),
						started_at='unknown',
						completed_at='unknown',
					)
					print(f'[PARENT] Task {os.path.basename(task_file)} failed to parse: {str(e)}')
					print(f'[PARENT] Full stdout was: {stdout.decode()[:500]}')
			else:
				stderr_text = stderr.decode().strip()
				_, task, judge_context, max_steps = load_task_definition(task_file)
				result = BenchmarkTaskArtifact(
					task_name=task_name,
					task_file=os.path.abspath(task_file),
					task=task,
					judge_context=judge_context,
					max_steps=max_steps,
					status=RunStatus.FAILED,
					verdict=False,
					counted_as_pass=False,
					explanation=f'Subprocess failed (code {proc.returncode}): {stderr_text[:200]}',
					failure_category=FailureCategory.SUBPROCESS_ERROR,
					commit_sha=detect_commit_sha(),
					started_at='unknown',
					completed_at='unknown',
				)
				print(f'[PARENT] Task {os.path.basename(task_file)} subprocess failed with code {proc.returncode}')
				if stderr_text:
					print(f'[PARENT] stderr: {stderr_text[:1000]}')
				stdout_text = stdout.decode().strip()
				if stdout_text:
					print(f'[PARENT] stdout: {stdout_text[:1000]}')
		except Exception as e:
			_, task, judge_context, max_steps = load_task_definition(task_file)
			result = BenchmarkTaskArtifact(
				task_name=task_name,
				task_file=os.path.abspath(task_file),
				task=task,
				judge_context=judge_context,
				max_steps=max_steps,
				status=RunStatus.FAILED,
				verdict=False,
				counted_as_pass=False,
				explanation=f'Failed to start subprocess: {str(e)}',
				failure_category=FailureCategory.STARTUP_ERROR,
				commit_sha=detect_commit_sha(),
				started_at='unknown',
				completed_at='unknown',
			)
			print(f'[PARENT] Failed to start subprocess for {os.path.basename(task_file)}: {str(e)}')

		result = result.model_copy(update={'artifact_path': str(write_task_artifact(results_dir, result))})
		return result


async def main(task_dir: str, results_dir: str, max_parallel: int, resume: bool):
	"""Run all tasks in parallel using subprocesses"""
	run_started_at = utc_now_iso()
	semaphore = asyncio.Semaphore(max_parallel)
	task_files = discover_task_files(task_dir)

	print(f'Found task files: {task_files}')

	if not task_files:
		print('No task files found!')
		return 0, 0

	# Run all tasks in parallel subprocesses
	tasks = [run_task_subprocess(task_file, semaphore, results_dir, resume) for task_file in task_files]
	results = await asyncio.gather(*tasks)

	passed = sum(1 for r in results if r.counted_as_pass)
	total = len(results)
	run_completed_at = utc_now_iso()
	report = build_run_report(
		task_dir=task_dir,
		results_dir=results_dir,
		started_at=run_started_at,
		completed_at=run_completed_at,
		artifacts=results,
		commit_sha=detect_commit_sha(),
	)
	report_path = write_run_report(results_dir, report)

	print('\n' + '=' * 60)
	print(f'{"RESULTS":^60}\n')

	# Prepare table data
	headers = ['Task', 'Status', 'Category', 'Reason']
	rows = []
	for r in results:
		status = '✅' if r.counted_as_pass else ('⏭️' if r.status == RunStatus.SKIPPED else '❌')
		rows.append([r.task_name, status, r.failure_category.value, r.explanation])

	# Calculate column widths
	col_widths = [max(len(str(row[i])) for row in ([headers] + rows)) for i in range(4)]

	# Print header
	header_row = ' | '.join(headers[i].ljust(col_widths[i]) for i in range(4))
	print(header_row)
	print('-+-'.join('-' * w for w in col_widths))

	# Print rows
	for row in rows:
		print(' | '.join(str(row[i]).ljust(col_widths[i]) for i in range(4)))

	print('\n' + '=' * 60)
	print(f'\n{"SCORE":^60}')
	print(f'\n{"=" * 60}\n')
	print(f'\n{"*" * 10}  {passed}/{total} PASSED  {"*" * 10}\n')
	print(f'Raw verdict pass rate: {report.pass_rate}%')
	print(f'Counted pass rate: {report.counted_pass_rate}%')
	print(f'Skipped tasks: {report.skipped_count}')
	print(f'Resumed tasks: {report.resumed_count}')
	print(f'Summary artifact: {report_path}')
	print('=' * 60 + '\n')

	# Output results for GitHub Actions
	print(f'PASSED={passed}')
	print(f'TOTAL={total}')

	# Output detailed results as JSON for GitHub Actions
	detailed_results = []
	for r in results:
		detailed_results.append(
			{
				'task': r.task_name,
				'success': r.counted_as_pass,
				'status': r.status.value,
				'category': r.failure_category.value,
				'reason': r.explanation,
				'artifact_path': r.artifact_path,
			}
		)

	print('DETAILED_RESULTS=' + json.dumps(detailed_results))
	print('RUN_SUMMARY=' + json.dumps(report.model_dump(mode='json')))

	return passed, total


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument('--task', type=str, help='Path to a single task YAML file (for subprocess mode)')
	parser.add_argument('--task-dir', type=str, default=get_default_task_dir(), help='Directory containing task YAML files')
	parser.add_argument('--results-dir', type=str, default=str(DEFAULT_RESULTS_DIR), help='Directory for task artifacts and summary output')
	parser.add_argument('--max-parallel', type=int, default=MAX_PARALLEL, help='Maximum parallel subprocesses')
	parser.add_argument('--no-resume', action='store_true', help='Disable task-level artifact reuse')
	args = parser.parse_args()

	if args.task:
		# Subprocess mode: run a single task and output ONLY JSON
		try:
			result = asyncio.run(run_single_task(args.task, args.results_dir, resume=not args.no_resume))
			# Output ONLY the JSON result, nothing else
			print(result.model_dump_json())
		except Exception as e:
			# Even on critical failure, output valid JSON
			_, task, judge_context, max_steps = load_task_definition(args.task)
			error_result = BenchmarkTaskArtifact(
				task_name=os.path.splitext(os.path.basename(args.task))[0],
				task_file=os.path.abspath(args.task),
				task=task,
				judge_context=judge_context,
				max_steps=max_steps,
				status=RunStatus.FAILED,
				verdict=False,
				counted_as_pass=False,
				explanation=f'Critical subprocess error: {str(e)}',
				failure_category=FailureCategory.STARTUP_ERROR,
				commit_sha=detect_commit_sha(),
				started_at='unknown',
				completed_at='unknown',
			)
			print(error_result.model_dump_json())
	else:
		# Parent process mode: run all tasks in parallel subprocesses
		passed, total = asyncio.run(
			main(
				task_dir=args.task_dir,
				results_dir=args.results_dir,
				max_parallel=args.max_parallel,
				resume=not args.no_resume,
			)
		)
		# Results already printed by main() function

		# Fail if 0% pass rate (all tasks failed)
		if total > 0 and passed == 0:
			print('\n❌ CRITICAL: 0% pass rate - all tasks failed!')
			sys.exit(1)
