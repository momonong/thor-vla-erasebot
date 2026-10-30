"""Bounded sequential launcher: six model/image jobs, at most 45 minutes total."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", nargs="+", choices=["ocr_llm", "vlm"], default=["ocr_llm", "vlm"])
    parser.add_argument("--max-batch-s", type=int, default=2700)
    parser.add_argument("--reason", default="first_attempt")
    args = parser.parse_args()
    if not 1 <= args.max_batch_s <= 2700:
        parser.error("max-batch-s must be between 1 and 2700")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_dir = HERE / "runs" / stamp
    batch_dir.mkdir(parents=True, exist_ok=False)
    ledger = {"started_utc": stamp, "max_batch_s": args.max_batch_s, "max_job_s": 900, "reason": args.reason, "jobs": []}
    start = time.monotonic()
    for route in args.routes:
        for image in ("colour", "fruits", "english"):
            remaining = args.max_batch_s - (time.monotonic() - start)
            if remaining <= 0:
                ledger["stop_reason"] = "batch_time_budget"
                break
            run_dir = batch_dir / f"{route}-{image}"
            cmd = [sys.executable, str(HERE / "runner.py"), "infer", "--route", route,
                   "--image", image, "--run-dir", str(run_dir)]
            job_start = time.monotonic()
            with (batch_dir / f"{route}-{image}.stdout.txt").open("w", encoding="utf-8") as out, \
                 (batch_dir / f"{route}-{image}.stderr.txt").open("w", encoding="utf-8") as err:
                try:
                    result = subprocess.run(cmd, stdout=out, stderr=err, timeout=min(900, remaining))
                    state = {"returncode": result.returncode}
                except subprocess.TimeoutExpired:
                    state = {"returncode": None, "technical_error": "subprocess_timeout"}
            job = {"route": route, "image": image, "elapsed_s": time.monotonic() - job_start,
                   "run_dir": str(run_dir), **state}
            ledger["jobs"].append(job)
            (batch_dir / "ledger.json").write_text(json.dumps(ledger, indent=2), encoding="utf-8")
            print(json.dumps(job), flush=True)
    ledger["total_s"] = time.monotonic() - start
    (batch_dir / "ledger.json").write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    print(json.dumps({"batch_dir": str(batch_dir), "total_s": ledger["total_s"]}), flush=True)


if __name__ == "__main__":
    main()
