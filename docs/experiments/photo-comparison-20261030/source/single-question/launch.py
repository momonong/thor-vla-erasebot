"""36 sequential fresh processes, 900s/job, 2700s/batch, technical retry at most once."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

import adapter

HERE = Path(__file__).resolve().parent


def main():
    started = time.monotonic()
    data = adapter.load_runner().questions()
    manifest = adapter.read(HERE / "baseline-manifest.json")
    adapter.check_light_manifest(manifest)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch = HERE / "runs" / stamp
    batch.mkdir(parents=True, exist_ok=False)
    runner = adapter.load_runner()
    ledger = {"started_utc": stamp, "max_batch_s": 2700, "max_job_s": 900, "declared_jobs": 36,
              "baseline_manifest_sha256": adapter.sha(HERE / "baseline-manifest.json"),
              "adapter_sha256": adapter.sha(HERE / "adapter.py"), "launcher_sha256": adapter.sha(Path(__file__)),
              "jobs": [], "group_progress": []}
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1"})
    budget_exhausted = False
    for route in ("ocr_llm", "vlm"):
        for image in data["images"]:
            for question in image["questions"]:
                job = {"route": route, "image_id": image["id"], "question_id": question["id"], "attempts": []}
                for attempt in (1, 2):
                    remaining = 2700 - (time.monotonic() - started)
                    if remaining <= 0:
                        job["status"] = "not_run_batch_budget"
                        budget_exhausted = True
                        break
                    run_dir = batch / f"{route}-{image['id']}" / question["id"] / f"attempt-{attempt}"
                    run_dir.parent.mkdir(parents=True, exist_ok=True)
                    command = [sys.executable, "-B", str(HERE / "adapter.py"), "--route", route,
                               "--image", image["id"], "--question", question["id"], "--run-dir", str(run_dir)]
                    t0 = time.monotonic()
                    state = {}
                    with (run_dir.parent / f"attempt-{attempt}.stdout.txt").open("w", encoding="utf-8") as out, \
                         (run_dir.parent / f"attempt-{attempt}.stderr.txt").open("w", encoding="utf-8") as err:
                        try:
                            result = subprocess.run(command, stdout=out, stderr=err, env=env, timeout=min(900, remaining))
                            state["returncode"] = result.returncode
                        except subprocess.TimeoutExpired:
                            state.update(returncode=None, technical_error="subprocess_timeout")
                    state.update(attempt=attempt, run_dir=str(run_dir), process_wall_s=time.monotonic() - t0)
                    result_path = run_dir / "result.json"
                    result = adapter.read(result_path) if result_path.exists() else None
                    state["inference_status"] = result.get("status") if result else "no_result"
                    state["strict_schema_valid"] = result.get("parsed", {}).get("valid") if result else None
                    technical = state.get("technical_error") or (result and result.get("status") == "technical_error")
                    job["attempts"].append(state)
                    job["effective_run_dir"] = str(run_dir)
                    job["status"] = "completed" if result and result["status"] == "completed" and state["returncode"] == 0 else "technical_failure"
                    if not technical or attempt == 2:
                        break
                ledger["jobs"].append(job)
                ledger["elapsed_s"] = time.monotonic() - started
                runner.dump(batch / "ledger.json", ledger)
                print(json.dumps({"question": question["id"], "route": route, "status": job["status"],
                                  "elapsed_s": ledger["elapsed_s"], "run_dir": job.get("effective_run_dir")}), flush=True)
            group = {"route": route, "image_id": image["id"], "jobs_recorded": 6,
                     "elapsed_s": time.monotonic() - started, "path": str(batch / f"{route}-{image['id']}")}
            ledger["group_progress"].append(group)
            runner.dump(batch / "ledger.json", ledger)
            print(json.dumps({"group_complete": group}), flush=True)
    ledger["total_s"] = time.monotonic() - started
    ledger["stop_reason"] = "batch_time_budget" if budget_exhausted else "all_declared_jobs_processed"
    runner.dump(batch / "ledger.json", ledger)
    print(json.dumps({"batch": str(batch), "jobs": len(ledger["jobs"]), "total_s": ledger["total_s"], "stop_reason": ledger["stop_reason"]}), flush=True)


if __name__ == "__main__":
    main()
