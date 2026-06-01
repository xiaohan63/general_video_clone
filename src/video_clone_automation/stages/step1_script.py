from __future__ import annotations

import json
import re

from video_clone_automation.config import AppConfig
from video_clone_automation.models import StageResult
from video_clone_automation.utils.files import load_json, load_text, path_exists, write_json
from video_clone_automation.utils.progress import progress_heartbeat, progress_log


def run_step1(
    config: AppConfig,
    *,
    rewrite_provider: object,
    progress: object | None = None,
) -> StageResult:
    input_video = config.resolve_step_path("step1", "input_video")
    script_output_path = config.resolve_step_path("step1", "script_output_path")
    skip_if_exists = bool(config.get("steps", "step1", "skip_if_exists", default=True))
    if skip_if_exists and path_exists(script_output_path):
        progress_log(progress, f"复用已有剧本 JSON：{script_output_path}", stage="step1")
        return StageResult(
            stage_name="step1",
            output_path=str(script_output_path),
            payload=load_json(script_output_path),
        )

    rewrite_prompt = load_text(config.resolve_step_path("step1", "rewrite_prompt_path"))
    extra_context = config.get("steps", "step1", "extra_context", default={})
    user_query = config.get("steps", "step1", "user_query", default="")
    schema_path = config.resolve_path(config.get("steps", "step1", "output_schema_path"))
    response_format = build_response_format(schema_path) if path_exists(schema_path) else None

    progress_log(progress, f"调用剧本仿写模型，输入视频 {input_video}", stage="step1")
    rewrite_payload = {
        "input_video": str(input_video),
        "input_text": build_step1_user_text(
            user_query=user_query,
            extra_context=extra_context,
        ),
        "response_format": response_format,
    }
    with progress_heartbeat(progress, "剧本仿写模型仍在运行，继续等待", stage="step1"):
        rewrite_result = generate_validated_rewrite(
            rewrite_provider=rewrite_provider,
            rewrite_prompt=rewrite_prompt,
            rewrite_payload=rewrite_payload,
            progress=progress,
        )
    write_json(script_output_path, rewrite_result)
    progress_log(progress, f"剧本 JSON 已写入 {script_output_path}", stage="step1")

    return StageResult(
        stage_name="step1",
        output_path=str(script_output_path),
        payload=rewrite_result,
    )


def generate_validated_rewrite(
    *,
    rewrite_provider: object,
    rewrite_prompt: str,
    rewrite_payload: dict[str, object],
    progress: object | None = None,
) -> dict[str, object]:
    result = rewrite_provider.generate_json(
        task_name="step1_rewrite",
        prompt=rewrite_prompt,
        payload=rewrite_payload,
    )
    issues = validate_step1_rewrite(result)
    if not issues:
        return result

    progress_log(
        progress,
        "剧本 JSON 未通过结构校验：" + "；".join(issues[:3]),
        stage="step1",
    )
    raise ValueError("Step1 rewrite result failed validation: " + "; ".join(issues))


def validate_step1_rewrite(result: dict[str, object]) -> list[str]:
    issues: list[str] = []
    character_names = collect_design_names(result, "character_design")
    scene_names = collect_design_names(result, "scene_design")
    prop_names = collect_design_names(result, "prop_design")

    breakdown = result.get("script_breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        return ["script_breakdown 必须是非空数组"]

    seen_segment_ids: set[int] = set()
    for index, segment in enumerate(breakdown, start=1):
        if not isinstance(segment, dict):
            issues.append(f"第 {index} 个分幕不是对象")
            continue

        segment_id = segment.get("segment_id", index)
        if isinstance(segment_id, int):
            if segment_id in seen_segment_ids:
                issues.append(f"segment_id {segment_id} 重复")
            seen_segment_ids.add(segment_id)

        duration_seconds = parse_duration_seconds(str(segment.get("duration", "")))
        if duration_seconds is not None and duration_seconds > 15:
            issues.append(f"segment_id {segment_id} duration 超过 15 秒：{segment.get('duration')}")

        range_seconds = parse_time_range_seconds(str(segment.get("time_range", "")))
        if range_seconds is not None and range_seconds > 15:
            issues.append(f"segment_id {segment_id} time_range 超过 15 秒：{segment.get('time_range')}")

        issues.extend(validate_references(segment, "characters", character_names, segment_id))
        issues.extend(validate_references(segment, "scenes", scene_names, segment_id))
        issues.extend(validate_references(segment, "props", prop_names, segment_id))

    return issues


def collect_design_names(result: dict[str, object], field_name: str) -> set[str]:
    values = result.get(field_name, [])
    if not isinstance(values, list):
        return set()
    names: set[str] = set()
    for value in values:
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            names.add(value["name"])
    return names


def validate_references(
    segment: dict[str, object],
    field_name: str,
    allowed_names: set[str],
    segment_id: object,
) -> list[str]:
    values = segment.get(field_name, [])
    if not isinstance(values, list):
        return [f"segment_id {segment_id} 的 {field_name} 必须是数组"]
    issues: list[str] = []
    for value in values:
        if not isinstance(value, str):
            issues.append(f"segment_id {segment_id} 的 {field_name} 包含非字符串引用")
        elif value not in allowed_names:
            issues.append(f"segment_id {segment_id} 引用了未定义的 {field_name}：{value}")
    return issues


def parse_duration_seconds(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def parse_time_range_seconds(text: str) -> float | None:
    match = re.search(
        r"(?P<start_min>\d{1,2}):(?P<start_sec>\d{2})\s*[-~—至到]\s*"
        r"(?P<end_min>\d{1,2}):(?P<end_sec>\d{2})",
        text,
    )
    if not match:
        return None
    start = int(match.group("start_min")) * 60 + int(match.group("start_sec"))
    end = int(match.group("end_min")) * 60 + int(match.group("end_sec"))
    if end < start:
        return None
    return float(end - start)


def build_step1_user_text(
    *,
    user_query: str,
    extra_context: dict[str, object],
) -> str:
    blocks = [
        "请基于我提供的原视频完成反解与仿写重构，并严格输出为合法纯 JSON。",
        f"用户修改 query：{user_query or '无额外修改要求'}",
    ]
    if extra_context:
        blocks.append(
            "额外上下文：\n"
            + json.dumps(extra_context, ensure_ascii=False, indent=2)
        )
    return "\n\n".join(blocks)


def build_response_format(schema_path: object) -> dict[str, object] | None:
    if not schema_path:
        return None
    schema = load_json(schema_path)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "video_clone_script",
            "strict": True,
            "schema": schema,
        },
    }
