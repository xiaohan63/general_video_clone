from __future__ import annotations

import json

from video_clone_automation.config import AppConfig
from video_clone_automation.models import StageResult
from video_clone_automation.utils.files import load_json, load_text, path_exists, write_json
from video_clone_automation.utils.progress import progress_heartbeat, progress_log


def run_step2(
    config: AppConfig,
    *,
    planning_provider: object,
    progress: object | None = None,
) -> StageResult:
    input_script_path = config.resolve_step_path("step2", "input_script_path")
    plan_output_path = config.resolve_step_path("step2", "plan_output_path")
    skip_if_exists = bool(config.get("steps", "step2", "skip_if_exists", default=True))
    if skip_if_exists and path_exists(plan_output_path):
        progress_log(progress, f"复用已有视觉规划 JSON：{plan_output_path}", stage="step2")
        return StageResult(
            stage_name="step2",
            output_path=str(plan_output_path),
            payload=load_json(plan_output_path),
        )

    planning_prompt = load_text(config.resolve_step_path("step2", "planning_prompt_path"))
    schema_path = config.resolve_path(config.get("steps", "step2", "output_schema_path"))
    video_aspect_ratio = config.video_aspect_ratio()

    script_payload = load_json(input_script_path)
    segment_count = len(script_payload.get("script_breakdown", []))
    progress_log(
        progress,
        f"调用视觉规划模型，分幕数={segment_count}，aspect_ratio={video_aspect_ratio or '未设置'}",
        stage="step2",
    )
    with progress_heartbeat(progress, "视觉规划模型仍在运行，继续等待", stage="step2"):
        planning_result = planning_provider.generate_json(
            task_name="step2_visual_plan",
            prompt=planning_prompt,
            payload={
                "script": script_payload,
                "video_aspect_ratio": video_aspect_ratio,
                "input_text": build_step2_user_text(
                    script_payload,
                    video_aspect_ratio=video_aspect_ratio,
                ),
                "response_format": build_response_format(schema_path) if path_exists(schema_path) else None,
            },
        )
    write_json(plan_output_path, planning_result)
    progress_log(progress, f"视觉规划 JSON 已写入 {plan_output_path}", stage="step2")

    return StageResult(
        stage_name="step2",
        output_path=str(plan_output_path),
        payload=planning_result,
    )


def build_step2_user_text(
    script_payload: dict[str, object],
    *,
    video_aspect_ratio: str | None = None,
) -> str:
    context_lines = []
    if video_aspect_ratio:
        context_lines.append(f"目标视频画面比例 video_aspect_ratio：{video_aspect_ratio}")

    context_text = ""
    if context_lines:
        context_text = "\n".join(context_lines) + "\n\n"

    return (
        context_text +
        "下面是完整剧本 JSON，请基于该剧本生成素材图 prompt 和分幕参考图规划，"
        "并严格输出为合法纯 JSON。\n\n"
        + json.dumps(script_payload, ensure_ascii=False, indent=2)
    )


def build_response_format(schema_path: object) -> dict[str, object] | None:
    if not schema_path:
        return None
    schema = load_json(schema_path)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "video_visual_plan",
            "strict": True,
            "schema": schema,
        },
    }
