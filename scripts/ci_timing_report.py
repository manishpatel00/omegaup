#!/usr/bin/env python3
"""
CI Timing Report Script for omegaup
Queries GitHub Actions API for workflow runs and extracts per-step and per-spec
durations for Cypress matrix shards.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
SPEC_PATTERN = re.compile(r'│\s*[✔✖]\s*([a-zA-Z0-9_]+\.cy\.ts)\s+([0-9:]+|[0-9]+ms)\s+')

def parse_iso(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def parse_spec_time(t_str):
    t_str = t_str.strip()
    if t_str.endswith("ms"):
        return float(t_str[:-2]) / 1000.0
    parts = t_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return float(t_str)

def get_run_list(repo, workflow, status, limit):
    cmd = [
        "gh", "run", "list",
        "--repo", repo,
        "--workflow", workflow,
        "--status", status,
        "-L", str(limit),
        "--json", "databaseId,event,headBranch,headSha,conclusion,createdAt"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error fetching run list: {res.stderr}", file=sys.stderr)
        return []
    return json.loads(res.stdout)

def get_job_data(repo, run_id):
    cmd = ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error fetching jobs for run {run_id}: {res.stderr}", file=sys.stderr)
        return []
    data = json.loads(res.stdout)
    return data.get("jobs", [])

def get_spec_timings(repo, run_id):
    cmd = ["gh", "run", "view", str(run_id), "--repo", repo, "--log"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    spec_times = {}
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            clean = ANSI_ESCAPE.sub('', line)
            m = SPEC_PATTERN.search(clean)
            if m:
                spec_name = m.group(1)
                dur = parse_spec_time(m.group(2))
                spec_times[spec_name] = dur
    return spec_times

def main():
    parser = argparse.ArgumentParser(description="Extract CI timing report for Cypress shards")
    parser.add_argument("--repo", default="omegaup/omegaup", help="GitHub repository")
    parser.add_argument("--workflow", default="ci.yml", help="Workflow name")
    parser.add_argument("--limit", type=int, default=10, help="Number of successful runs to analyze")
    parser.add_argument("--out", default=None, help="Output JSON file")
    args = parser.parse_args()

    runs = get_run_list(args.repo, args.workflow, "success", args.limit)
    print(f"Found {len(runs)} successful runs in {args.repo} for {args.workflow}", file=sys.stderr)

    runs_meta = []
    cypress_step_durations = defaultdict(lambda: defaultdict(list))
    total_shard_durations = defaultdict(list)
    spec_durations = defaultdict(list)
    prepare_env_durations = defaultdict(list)

    for idx, r in enumerate(runs, 1):
        run_id = r["databaseId"]
        print(f"[{idx}/{len(runs)}] Processing run {run_id} ({r.get('headBranch')})...", file=sys.stderr)
        runs_meta.append({
            "run_id": run_id,
            "event": r.get("event"),
            "head_branch": r.get("headBranch"),
            "head_sha": r.get("headSha"),
            "created_at": r.get("createdAt"),
        })

        jobs = get_job_data(args.repo, run_id)
        for job in jobs:
            job_name = job.get("name", "")
            for step in job.get("steps", []):
                s_name = step.get("name", "")
                if s_name == "Prepare Environment":
                    s_start = parse_iso(step.get("started_at"))
                    s_end = parse_iso(step.get("completed_at"))
                    if s_start and s_end:
                        sec = (s_end - s_start).total_seconds()
                        prepare_env_durations[job_name].append(sec)

            if job_name.startswith("cypress"):
                start = parse_iso(job.get("started_at"))
                end = parse_iso(job.get("completed_at"))
                if start and end:
                    total_shard_durations[job_name].append((end - start).total_seconds())

                for step in job.get("steps", []):
                    s_name = step.get("name", "")
                    s_start = parse_iso(step.get("started_at"))
                    s_end = parse_iso(step.get("completed_at"))
                    if s_start and s_end:
                        cypress_step_durations[job_name][s_name].append((s_end - s_start).total_seconds())

        specs = get_spec_timings(args.repo, run_id)
        for s_name, s_dur in specs.items():
            spec_durations[s_name].append(s_dur)

    report = {
        "repo": args.repo,
        "workflow": args.workflow,
        "runs": runs_meta,
        "prepare_env_by_job": {k: v for k, v in prepare_env_durations.items()},
        "total_shard_durations": {k: v for k, v in total_shard_durations.items()},
        "cypress_step_durations": {k: dict(v) for k, v in cypress_step_durations.items()},
        "spec_durations": {k: v for k, v in spec_durations.items()}
    }

    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {args.out}", file=sys.stderr)
    else:
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
