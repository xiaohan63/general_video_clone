from __future__ import annotations

import argparse
import json
import sys
import traceback

from video_clone_automation.config import load_config
from video_clone_automation.pipelines.run_pipeline import run_pipeline
from video_clone_automation.utils.env import load_dotenv_if_exists
from video_clone_automation.utils.progress import ProgressReporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Video clone automation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one step or the full pipeline")
    run_parser.add_argument("--config", required=True, help="Path to config JSON")
    run_parser.add_argument(
        "--step",
        choices=["step1", "step2", "step3", "step4", "step5", "all"],
        default="all",
        help="Step to run",
    )
    run_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable realtime progress logs",
    )
    run_parser.add_argument(
        "--debug-traceback",
        action="store_true",
        help="Print the full Python traceback when a run fails",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        try:
            config = load_config(args.config)
            load_dotenv_if_exists(config.root_dir)
            progress = ProgressReporter(enabled=not args.no_progress)
            progress.log(
                f"开始运行 pipeline，video_name={config.video_name()}，step={args.step}"
            )
            results = run_pipeline(config, args.step, progress=progress)
            progress.log("pipeline 运行完成")
            summary = [
                {
                    "stage_name": result.stage_name,
                    "output_path": result.output_path,
                }
                for result in results
            ]
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        except Exception as exc:
            if args.debug_traceback:
                traceback.print_exc()
            else:
                print(f"运行失败：{exc}", file=sys.stderr)
                print("如需查看完整 Python traceback，请加 --debug-traceback。", file=sys.stderr)
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
