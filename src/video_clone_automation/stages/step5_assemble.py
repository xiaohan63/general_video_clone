from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from video_clone_automation.config import AppConfig
from video_clone_automation.models import StageResult
from video_clone_automation.utils.files import ensure_parent_dir, load_json, write_json
from video_clone_automation.utils.progress import progress_log


def run_step5(
    config: AppConfig,
    *,
    progress: object | None = None,
) -> StageResult:
    input_manifest_path = config.resolve_step_path("step5", "input_manifest_path")
    final_video_path = config.resolve_step_path("step5", "final_video_path")
    final_video_manifest_path = config.resolve_step_path("step5", "final_video_manifest_path")
    skip_if_exists = bool(config.get("steps", "step5", "skip_if_exists", default=True))
    concat_options = config.get("steps", "step5", "concat_options", default={})
    if not isinstance(concat_options, dict):
        raise ValueError("steps.step5.concat_options must be an object")

    manifest_payload = load_json(input_manifest_path)
    segments = sorted_video_segments(manifest_payload)
    if not segments:
        raise ValueError(f"No video segments found in {input_manifest_path}")

    existing_final_manifest = load_json(final_video_manifest_path) if final_video_manifest_path.exists() else None
    if (
        skip_if_exists
        and final_video_path.exists()
        and isinstance(existing_final_manifest, dict)
        and existing_final_manifest.get("status") == "assembled"
        and str(existing_final_manifest.get("final_video_path") or existing_final_manifest.get("assembled_video_path"))
        == str(final_video_path)
    ):
        progress_log(progress, f"复用已有长视频：{final_video_path}", stage="step5")
        return StageResult(
            stage_name="step5",
            output_path=str(final_video_manifest_path),
            payload=existing_final_manifest,
        )

    missing_segments = missing_segment_paths(segments)
    allow_planned_segments = bool(concat_options.get("allow_planned_segments", True))
    if missing_segments:
        if allow_planned_segments and all(str(segment.get("status", "")).lower() == "planned" for segment in segments):
            planned_payload = build_final_manifest(
                source_payload=manifest_payload,
                segments=segments,
                final_video_path=final_video_path,
                status="planned",
                extra={
                    "missing_segment_paths": [str(path) for path in missing_segments],
                    "message": "视频片段仍是 planned 状态，尚未生成真实文件；step5 已生成待拼接清单。",
                },
            )
            write_json(final_video_manifest_path, planned_payload)
            progress_log(progress, f"视频片段尚未落盘，已写入待拼接清单：{final_video_manifest_path}", stage="step5")
            return StageResult(
                stage_name="step5",
                output_path=str(final_video_manifest_path),
                payload=planned_payload,
            )
        raise FileNotFoundError(
            "Cannot assemble final video because segment files are missing: "
            + ", ".join(str(path) for path in missing_segments)
        )

    ffmpeg_binary = str(concat_options.get("ffmpeg_binary", "ffmpeg"))
    if shutil.which(ffmpeg_binary) is None:
        raise RuntimeError(
            f"ffmpeg not found: {ffmpeg_binary}. Install ffmpeg or set steps.step5.concat_options.ffmpeg_binary."
        )

    progress_log(progress, f"开始拼接 {len(segments)} 个视频片段 -> {final_video_path}", stage="step5")
    assemble_with_ffmpeg(
        ffmpeg_binary=ffmpeg_binary,
        segment_paths=[Path(str(segment["output_path"])).resolve() for segment in segments],
        output_path=final_video_path,
        reencode_on_copy_failure=bool(concat_options.get("reencode_on_copy_failure", True)),
        progress=progress,
    )

    final_payload = build_final_manifest(
        source_payload=manifest_payload,
        segments=segments,
        final_video_path=final_video_path,
        status="assembled",
        extra={
            "concat_method": "ffmpeg_concat",
            "segment_count": len(segments),
        },
    )
    write_json(final_video_manifest_path, final_payload)
    progress_log(progress, f"长视频已生成：{final_video_path}", stage="step5")

    return StageResult(
        stage_name="step5",
        output_path=str(final_video_manifest_path),
        payload=final_payload,
    )


def sorted_video_segments(manifest_payload: dict[str, Any]) -> list[dict[str, Any]]:
    segments = manifest_payload.get("segments", [])
    if not isinstance(segments, list):
        raise ValueError("Manifest field 'segments' must be a list")

    normalized_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if segment.get("segment_id") is None:
            raise ValueError(f"Segment is missing segment_id: {segment}")
        if not segment.get("output_path"):
            raise ValueError(f"Segment is missing output_path: {segment}")
        normalized_segments.append(segment)

    return sorted(normalized_segments, key=lambda item: int(item["segment_id"]))


def missing_segment_paths(segments: list[dict[str, Any]]) -> list[Path]:
    missing = []
    for segment in segments:
        path = Path(str(segment["output_path"])).resolve()
        if not path.exists():
            missing.append(path)
    return missing


def assemble_with_ffmpeg(
    *,
    ffmpeg_binary: str,
    segment_paths: list[Path],
    output_path: Path,
    reencode_on_copy_failure: bool,
    progress: object | None = None,
) -> None:
    ensure_parent_dir(output_path)
    concat_list_path = output_path.with_suffix(".concat.txt")
    concat_list_path.write_text(
        "".join(format_concat_file_line(path) for path in segment_paths),
        encoding="utf-8",
    )
    try:
        copy_command = [
            ffmpeg_binary,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(output_path),
        ]
        copy_result = subprocess.run(copy_command, capture_output=True, text=True, check=False)
        if copy_result.returncode == 0:
            return

        if not reencode_on_copy_failure:
            raise RuntimeError(ffmpeg_error_message(copy_command, copy_result))

        progress_log(progress, "直接 concat 失败，改用重新编码方式拼接", stage="step5")
        reencode_command = [
            ffmpeg_binary,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        reencode_result = subprocess.run(reencode_command, capture_output=True, text=True, check=False)
        if reencode_result.returncode != 0:
            raise RuntimeError(ffmpeg_error_message(reencode_command, reencode_result))
    finally:
        concat_list_path.unlink(missing_ok=True)


def format_concat_file_line(path: Path) -> str:
    escaped_path = str(path).replace("'", "'\\''")
    return f"file '{escaped_path}'\n"


def ffmpeg_error_message(command: list[str], result: subprocess.CompletedProcess[str]) -> str:
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    details = stderr or stdout or "no ffmpeg output"
    return "ffmpeg failed: " + " ".join(command) + "\n" + details[-4000:]


def build_final_manifest(
    *,
    source_payload: dict[str, Any],
    segments: list[dict[str, Any]],
    final_video_path: Path,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "video_name": source_payload.get("video_name"),
        "segments": segments,
        "aspect_ratio": source_payload.get("aspect_ratio"),
        "final_video_path": str(final_video_path),
        "assembled_video_path": str(final_video_path),
        "status": status,
    }
    if extra:
        payload.update(extra)
    return payload
