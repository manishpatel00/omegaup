#!/usr/bin/env python3
"""
CI Timing Report for omegaup.

Queries the GitHub Actions API and extracts per-step and per-spec
durations for Cypress matrix shards across N successful workflow runs.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional


ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
SPEC_PATTERN = re.compile(
    r'│\s*[✔✖]\s*([a-zA-Z0-9_]+\.cy\.ts)\s+'
    r'([0-9:]+|[0-9]+ms)\s+'
)


def parse_iso(timestamp: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    if not timestamp:
        return None
    return datetime.fromisoformat(
        timestamp.replace('Z', '+00:00')
    ).astimezone(timezone.utc)


def parse_spec_time(time_str: str) -> float:
    """Convert a Cypress spec duration string to seconds."""
    time_str = time_str.strip()
    if time_str.endswith('ms'):
        return float(time_str[:-2]) / 1000.0
    parts = time_str.split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return (
            int(parts[0]) * 3600
            + int(parts[1]) * 60
            + int(parts[2])
        )
    return float(time_str)


def get_run_list(
    repo: str,
    workflow: str,
    status: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Return a list of workflow run metadata dicts."""
    cmd = [
        'gh', 'run', 'list',
        '--repo', repo,
        '--workflow', workflow,
        '--status', status,
        '-L', str(limit),
        '--json',
        'databaseId,event,headBranch,headSha,conclusion,createdAt',
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(
            f'Error fetching run list: {result.stderr}',
            file=sys.stderr,
        )
        return []
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def get_job_data(
    repo: str,
    run_id: int,
) -> list[dict[str, Any]]:
    """Return the list of jobs for a given workflow run."""
    endpoint = (
        f'repos/{repo}/actions/runs/{run_id}/jobs?per_page=100'
    )
    cmd = ['gh', 'api', endpoint]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(
            f'Error fetching jobs for run {run_id}: {result.stderr}',
            file=sys.stderr,
        )
        return []
    data: dict[str, Any] = json.loads(result.stdout)
    return data.get('jobs', [])


def get_spec_timings(
    repo: str,
    run_id: int,
) -> dict[str, float]:
    """Extract per-spec durations from the workflow run log output."""
    cmd = ['gh', 'run', 'view', str(run_id), '--repo', repo, '--log']
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False
    )
    spec_times: dict[str, float] = {}
    if result.returncode != 0:
        return spec_times
    for line in result.stdout.splitlines():
        clean = ANSI_ESCAPE.sub('', line)
        match = SPEC_PATTERN.search(clean)
        if match:
            spec_name = match.group(1)
            spec_times[spec_name] = parse_spec_time(match.group(2))
    return spec_times


def main() -> None:
    """Parse arguments, collect timing data, and emit a JSON report."""
    parser = argparse.ArgumentParser(
        description='Extract CI timing report for Cypress shards'
    )
    parser.add_argument(
        '--repo',
        default='omegaup/omegaup',
        help='GitHub repository (owner/name)',
    )
    parser.add_argument(
        '--workflow',
        default='ci.yml',
        help='Workflow filename',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Number of successful runs to analyze',
    )
    parser.add_argument(
        '--out',
        default=None,
        help='Output JSON file (stdout if omitted)',
    )
    args = parser.parse_args()

    runs = get_run_list(
        args.repo, args.workflow, 'success', args.limit
    )
    print(
        f'Found {len(runs)} successful runs in '
        f'{args.repo} for {args.workflow}',
        file=sys.stderr,
    )

    runs_meta: list[dict[str, Any]] = []
    cypress_step_durations: dict[str, dict[str, list[float]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    total_shard_durations: dict[str, list[float]] = defaultdict(list)
    spec_durations: dict[str, list[float]] = defaultdict(list)
    prepare_env_durations: dict[str, list[float]] = defaultdict(list)

    for idx, run in enumerate(runs, 1):
        run_id: int = run['databaseId']
        print(
            f'[{idx}/{len(runs)}] run {run_id}'
            f' ({run.get("headBranch")})...',
            file=sys.stderr,
        )
        runs_meta.append({
            'run_id': run_id,
            'event': run.get('event'),
            'head_branch': run.get('headBranch'),
            'head_sha': run.get('headSha'),
            'created_at': run.get('createdAt'),
        })

        jobs = get_job_data(args.repo, run_id)
        for job in jobs:
            job_name: str = job.get('name', '')

            for step in job.get('steps', []):
                step_name: str = step.get('name', '')
                if step_name == 'Prepare Environment':
                    step_start = parse_iso(step.get('started_at'))
                    step_end = parse_iso(step.get('completed_at'))
                    if step_start and step_end:
                        sec = (step_end - step_start).total_seconds()
                        prepare_env_durations[job_name].append(sec)

            if not job_name.startswith('cypress'):
                continue

            job_start = parse_iso(job.get('started_at'))
            job_end = parse_iso(job.get('completed_at'))
            if job_start and job_end:
                total_shard_durations[job_name].append(
                    (job_end - job_start).total_seconds()
                )

            for step in job.get('steps', []):
                step_name = step.get('name', '')
                step_start = parse_iso(step.get('started_at'))
                step_end = parse_iso(step.get('completed_at'))
                if step_start and step_end:
                    cypress_step_durations[job_name][step_name].append(
                        (step_end - step_start).total_seconds()
                    )

        specs = get_spec_timings(args.repo, run_id)
        for spec_name, spec_dur in specs.items():
            spec_durations[spec_name].append(spec_dur)

    report: dict[str, Any] = {
        'repo': args.repo,
        'workflow': args.workflow,
        'runs': runs_meta,
        'prepare_env_by_job': dict(prepare_env_durations.items()),
        'total_shard_durations': dict(total_shard_durations.items()),
        'cypress_step_durations': {
            k: dict(v)
            for k, v in cypress_step_durations.items()
        },
        'spec_durations': dict(spec_durations.items()),
    }

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as out_file:
            json.dump(report, out_file, indent=2)
        print(f'Report written to {args.out}', file=sys.stderr)
    else:
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
