from __future__ import annotations

from video_clone_automation.config import AppConfig
from video_clone_automation.models import StageResult
from video_clone_automation.registry import build_provider
from video_clone_automation.stages.step1_script import run_step1
from video_clone_automation.stages.step2_planning import run_step2
from video_clone_automation.stages.step3_images import run_step3
from video_clone_automation.stages.step4_video import run_step4
from video_clone_automation.stages.step5_assemble import run_step5
from video_clone_automation.utils.progress import progress_log


def run_pipeline(config: AppConfig, step: str, *, progress: object | None = None) -> list[StageResult]:
    results: list[StageResult] = []

    if step in {"step1", "all"} and config.step_enabled("step1"):
        progress_log(progress, "开始", stage="step1")
        results.append(
            run_step1(
                config,
                rewrite_provider=build_provider(config.provider_config("script_rewrite")),
                progress=progress,
            )
        )
        progress_log(progress, f"完成，输出 {results[-1].output_path}", stage="step1")

    if step in {"step2", "all"} and config.step_enabled("step2"):
        progress_log(progress, "开始", stage="step2")
        results.append(
            run_step2(
                config,
                planning_provider=build_provider(config.provider_config("visual_planner")),
                progress=progress,
            )
        )
        progress_log(progress, f"完成，输出 {results[-1].output_path}", stage="step2")

    if step in {"step3", "all"} and config.step_enabled("step3"):
        progress_log(progress, "开始", stage="step3")
        results.append(
            run_step3(
                config,
                asset_provider=build_provider(config.provider_config("asset_image")),
                reference_provider=build_provider(config.provider_config("reference_image")),
                progress=progress,
            )
        )
        progress_log(progress, f"完成，输出 {results[-1].output_path}", stage="step3")

    if step in {"step4", "all"} and config.step_enabled("step4"):
        progress_log(progress, "开始", stage="step4")
        results.append(
            run_step4(
                config,
                video_provider=build_provider(config.provider_config("video_segment")),
                progress=progress,
            )
        )
        progress_log(progress, f"完成，输出 {results[-1].output_path}", stage="step4")

    if step in {"step5", "all"} and config.step_enabled("step5"):
        progress_log(progress, "开始", stage="step5")
        results.append(run_step5(config, progress=progress))
        progress_log(progress, f"完成，输出 {results[-1].output_path}", stage="step5")

    return results
