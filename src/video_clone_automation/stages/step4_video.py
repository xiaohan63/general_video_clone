from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from video_clone_automation.config import AppConfig
from video_clone_automation.models import StageResult
from video_clone_automation.utils.files import load_json, load_text, write_json
from video_clone_automation.utils.naming import safe_filename
from video_clone_automation.utils.progress import progress_heartbeat, progress_log


def run_step4(
    config: AppConfig,
    *,
    video_provider: object,
    progress: object | None = None,
) -> StageResult:
    segment_output_path = config.resolve_step_path("step4", "segment_output_path")
    final_video_manifest_path = config.resolve_step_path("step4", "final_video_manifest_path")
    skip_if_exists = bool(config.get("steps", "step4", "skip_if_exists", default=True))
    script_path = config.resolve_step_path("step4", "input_script_path")
    input_generation_path = config.resolve_step_path("step4", "input_generation_path")
    video_output_dir = config.resolve_path(
        config.get("steps", "step4", "video_output_dir", default="data/output/{video_name}/step4/video_segments")
    )
    video_options = config.get("steps", "step4", "video_options", default={})
    video_aspect_ratio = config.video_aspect_ratio()
    selected_segment_ids = {
        int(segment_id)
        for segment_id in config.get("steps", "step4", "segment_ids", default=[])
    }

    script_payload = load_json(script_path)
    generation_payload = load_json(input_generation_path)
    references_by_segment = build_references_by_segment(generation_payload)
    existing_manifest = load_json(final_video_manifest_path) if final_video_manifest_path.exists() else None
    existing_segments_by_id = build_existing_segments_by_id(existing_manifest)

    script_segments = script_payload.get("script_breakdown", [])
    runnable_segments = [
        item
        for item in script_segments
        if not selected_segment_ids or int(item["segment_id"]) in selected_segment_ids
    ]
    expected_segment_ids = [int(item["segment_id"]) for item in runnable_segments]
    complete_segment_ids = {
        segment_id
        for segment_id in expected_segment_ids
        if is_complete_existing_segment(
            existing_segments_by_id.get(segment_id),
            build_segment_output_path(video_output_dir=video_output_dir, segment_id=segment_id),
        )
    }
    missing_segment_ids = [segment_id for segment_id in expected_segment_ids if segment_id not in complete_segment_ids]

    if skip_if_exists and existing_manifest and not missing_segment_ids:
        progress_log(
            progress,
            f"复用已有完整视频清单：{final_video_manifest_path}，分幕数={len(expected_segment_ids)}",
            stage="step4",
        )
        return StageResult(
            stage_name="step4",
            output_path=str(final_video_manifest_path),
            payload=existing_manifest,
        )

    if skip_if_exists and existing_manifest:
        progress_log(
            progress,
            f"已有视频清单不完整，复用 {len(complete_segment_ids)}/{len(expected_segment_ids)} 个分幕，补生成缺失分幕：{missing_segment_ids}",
            stage="step4",
        )

    video_prompt = load_text(config.resolve_step_path("step4", "video_prompt_path"))
    segments = []
    for index, script_segment in enumerate(runnable_segments, start=1):
        segment_id = int(script_segment["segment_id"])
        output_path = build_segment_output_path(
            video_output_dir=video_output_dir,
            segment_id=segment_id,
        )

        existing_segment = existing_segments_by_id.get(segment_id)
        if skip_if_exists and is_complete_existing_segment(existing_segment, output_path):
            progress_log(
                progress,
                f"复用已有视频片段 {index}/{len(runnable_segments)}：segment {segment_id} -> {existing_segment['output_path']}",
                stage="step4",
            )
            segments.append(existing_segment)
            continue

        reference_images = references_by_segment.get(segment_id, [])
        if not reference_images:
            raise ValueError(f"No reference images found for segment_id={segment_id}")

        prompt = build_video_prompt(
            base_prompt=video_prompt,
            script_segment=script_segment,
            reference_images=reference_images,
            video_aspect_ratio=video_aspect_ratio,
        )
        segment_duration = parse_duration_to_seconds(
            script_segment.get("duration"),
            fallback=video_options.get("duration"),
        )
        progress_log(
            progress,
            f"视频片段 {index}/{len(runnable_segments)}：segment {segment_id}，duration={segment_duration}，参考图={len(reference_images)}",
            stage="step4",
        )
        with progress_heartbeat(
            progress,
            f"视频片段仍在生成：segment {segment_id}",
            stage="step4",
        ):
            segment_result = video_provider.generate_video(
                task_name="step4_video_segment",
                prompt=prompt,
                payload={
                    "segment_id": segment_id,
                    "prompt": prompt,
                    "reference_image_paths": [item["output_path"] for item in reference_images],
                    "reference_image_ids": [item["reference_image_id"] for item in reference_images],
                    "output_path": str(output_path),
                    "duration": segment_duration,
                    "aspect_ratio": video_aspect_ratio,
                    "sound": video_options.get("sound"),
                    "audio": video_options.get("audio"),
                    "extra_body": video_options.get("extra_body", {}),
                    "skip_if_exists": skip_if_exists,
                    "progress": progress,
                },
            )
        progress_log(
            progress,
            f"视频片段完成：segment {segment_id} -> {segment_result['output_path']} ({segment_result.get('status', 'unknown')})",
            stage="step4",
        )
        segments.append(segment_result)

    segment_payload = {
        "video_name": config.video_name(),
        "aspect_ratio": video_aspect_ratio,
        "segments": segments,
    }
    final_manifest_payload = {
        "video_name": config.video_name(),
        "segments": segments,
        "aspect_ratio": video_aspect_ratio,
        "assembled_video_path": str(
            config.resolve_path(config.get("steps", "step4", "assembled_video_path", default="data/output/{video_name}/final_video.mp4"))
        ),
        "status": "segments_generated",
    }

    write_json(segment_output_path, segment_payload)
    write_json(final_video_manifest_path, final_manifest_payload)
    progress_log(progress, f"视频清单已写入 {final_video_manifest_path}", stage="step4")

    return StageResult(
        stage_name="step4",
        output_path=str(final_video_manifest_path),
        payload=final_manifest_payload,
    )


def build_existing_segments_by_id(manifest_payload: dict[str, object] | None) -> dict[int, dict[str, Any]]:
    if not manifest_payload:
        return {}

    segments_by_id: dict[int, dict[str, Any]] = {}
    for segment in manifest_payload.get("segments", []):
        if not isinstance(segment, dict) or segment.get("segment_id") is None:
            continue
        try:
            segment_id = int(segment["segment_id"])
        except (TypeError, ValueError):
            continue
        segments_by_id[segment_id] = segment
    return segments_by_id


def is_complete_existing_segment(segment: dict[str, Any] | None, expected_output_path: Path) -> bool:
    if not segment:
        return False

    output_path = Path(str(segment.get("output_path") or expected_output_path)).resolve()
    if output_path != expected_output_path.resolve():
        return False

    status = str(segment.get("status", "")).lower()
    if status == "planned":
        return True
    return output_path.exists()


def build_references_by_segment(generation_payload: dict[str, object]) -> dict[int, list[dict[str, str]]]:
    references_by_segment: dict[int, list[dict[str, str]]] = {}
    for segment in generation_payload.get("reference_image_plan", []):
        segment_id = int(segment["segment_id"])
        references_by_segment[segment_id] = [
            {
                "reference_image_id": item["reference_image_id"],
                "output_path": item["output_path"],
            }
            for item in segment.get("reference_images", [])
        ]
    return references_by_segment


def build_video_prompt(
    *,
    base_prompt: str,
    script_segment: dict[str, object],
    reference_images: list[dict[str, str]],
    video_aspect_ratio: str | None = None,
) -> str:
    reference_ids = "、".join(item["reference_image_id"] for item in reference_images)
    parts = [
        base_prompt.strip(),
        f"segment_id：{script_segment['segment_id']}",
        f"匹配的参考图 ID：{reference_ids}",
    ]
    if video_aspect_ratio:
        parts.append(f"目标视频画面比例：{video_aspect_ratio}")
    parts.extend(
        [
            "visual_dialogue：\n" + str(script_segment.get("visual_dialogue", "")),
            "style_and_texture：\n" + str(script_segment.get("style_and_texture", "")),
            "cinematography_and_editing：\n" + str(script_segment.get("cinematography_and_editing", "")),
            "请严格基于输入参考图保持人物、服装、道具、场景和构图一致，生成该分幕的视频片段；不要生成字幕、文字、水印或额外人物。",
        ]
    )
    return "\n\n".join(parts)


def parse_duration_to_seconds(value: Any, *, fallback: Any = None) -> int | float | None:
    if value is None or value == "":
        return parse_duration_to_seconds(fallback) if fallback is not None else None
    if isinstance(value, (int, float)):
        return value

    text = str(value).strip()
    if not text:
        return parse_duration_to_seconds(fallback) if fallback is not None else None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return parse_duration_to_seconds(fallback) if fallback is not None else None

    seconds = float(match.group(0))
    return int(seconds) if seconds.is_integer() else seconds


def build_segment_output_path(
    *,
    video_output_dir: Path | None,
    segment_id: int,
) -> Path:
    if video_output_dir is None:
        raise ValueError("video_output_dir cannot be None")
    return (video_output_dir / f"segment_{safe_filename(str(segment_id))}.mp4").resolve()
