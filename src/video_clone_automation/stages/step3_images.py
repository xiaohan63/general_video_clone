from __future__ import annotations

import shutil
from pathlib import Path

from video_clone_automation.config import AppConfig
from video_clone_automation.models import StageResult
from video_clone_automation.utils.files import ensure_parent_dir, load_json, write_json
from video_clone_automation.utils.naming import safe_filename
from video_clone_automation.utils.progress import progress_heartbeat, progress_log


def run_step3(
    config: AppConfig,
    *,
    asset_provider: object,
    reference_provider: object,
    progress: object | None = None,
) -> StageResult:
    input_plan_path = config.resolve_step_path("step3", "input_plan_path")
    generation_output_path = config.resolve_step_path("step3", "generation_output_path")
    skip_if_exists = bool(config.get("steps", "step3", "skip_if_exists", default=True))
    if skip_if_exists and generation_output_path.exists():
        progress_log(progress, f"复用已有图片生成清单：{generation_output_path}", stage="step3")
        return StageResult(
            stage_name="step3",
            output_path=str(generation_output_path),
            payload=load_json(generation_output_path),
        )

    asset_output_dir = config.resolve_path(
        config.get("steps", "step3", "asset_output_dir", default="data/output/{video_name}/step3/assets")
    )
    reference_output_dir = config.resolve_path(
        config.get("steps", "step3", "reference_output_dir", default="data/output/{video_name}/step3/reference_images")
    )
    image_options = config.get("steps", "step3", "image_options", default={})
    video_aspect_ratio = config.video_aspect_ratio()

    plan_payload = load_json(input_plan_path)
    generated_assets = {
        "character_images": [],
        "prop_images": [],
        "scene_images": [],
    }
    generated_references = []
    asset_lookup: dict[str, dict[str, str]] = {
        "characters": {},
        "props": {},
        "scenes": {},
    }
    reference_lookup: dict[str, str] = {}

    asset_groups = [
        ("character_images", "characters", "characters", "1024x1536"),
        ("prop_images", "props", "props", "1024x1024"),
        ("scene_images", "scenes", "scenes", "1536x1024"),
    ]
    total_assets = sum(
        len(plan_payload.get("asset_image_prompts", {}).get(group_key, []))
        for group_key, _, _, _ in asset_groups
    )
    generated_asset_count = 0

    for group_key, lookup_key, output_subdir, default_size in asset_groups:
        for asset in plan_payload.get("asset_image_prompts", {}).get(group_key, []):
            generated_asset_count += 1
            progress_log(
                progress,
                f"素材图 {generated_asset_count}/{total_assets}：{group_key} / {asset['name']}",
                stage="step3",
            )
            prompt = asset["generation_prompt"]
            if group_key == "scene_images":
                prompt = with_video_aspect_ratio(
                    prompt,
                    video_aspect_ratio,
                    target="场景图",
                )
            output_path = build_asset_output_path(
                asset_output_dir=asset_output_dir,
                subdir=output_subdir,
                name=asset["name"],
            )
            group_options = image_options.get(group_key, {})
            image_size = group_options.get("size", default_size)
            if group_key == "scene_images" and video_aspect_ratio:
                image_size = image_size_for_aspect_ratio(video_aspect_ratio, fallback=image_size)
            payload = {
                "name": asset["name"],
                "category": group_key,
                "prompt": prompt,
                "output_path": str(output_path),
                "size": image_size,
                "quality": group_options.get("quality"),
                "background": group_options.get("background"),
                "output_format": group_options.get("output_format", "png"),
                "skip_if_exists": skip_if_exists,
            }
            if group_key == "scene_images" and video_aspect_ratio:
                payload["aspect_ratio"] = video_aspect_ratio
            with progress_heartbeat(
                progress,
                f"素材图仍在生成：{group_key} / {asset['name']}",
                stage="step3",
            ):
                image_result = asset_provider.generate_image(
                    task_name=f"step3_{group_key}",
                    prompt=prompt,
                    payload=payload,
                )
            progress_log(
                progress,
                f"素材图完成：{asset['name']} -> {image_result['output_path']} ({image_result.get('status', 'unknown')})",
                stage="step3",
            )
            generated_assets[group_key].append(image_result)
            asset_lookup[lookup_key][asset["name"]] = image_result["output_path"]

    total_references = sum(
        len(segment.get("reference_images", []))
        for segment in plan_payload.get("reference_image_plan", [])
    )
    generated_reference_count = 0
    for segment in plan_payload.get("reference_image_plan", []):
        segment_result = {
            "segment_id": segment["segment_id"],
            "reference_image_count": segment["reference_image_count"],
            "reference_images": [],
        }
        for reference_image in segment.get("reference_images", []):
            generated_reference_count += 1
            progress_log(
                progress,
                f"关键帧 {generated_reference_count}/{total_references}：segment {segment['segment_id']} / {reference_image['reference_image_id']}",
                stage="step3",
            )
            output_path = build_reference_output_path(
                reference_output_dir=reference_output_dir,
                reference_image_id=reference_image["reference_image_id"],
            )
            reused_reference_image_id = reference_image.get("reused_reference_image_id")
            if reused_reference_image_id:
                if reused_reference_image_id not in reference_lookup:
                    raise ValueError(
                        f"Missing reused reference image source: {reused_reference_image_id}"
                    )
                copy_generated_reference(
                    source_path=Path(reference_lookup[reused_reference_image_id]),
                    target_path=output_path,
                )
                result = {
                    "reference_image_id": reference_image["reference_image_id"],
                    "reused_reference_image_id": reused_reference_image_id,
                    "reuse_reason": reference_image["reuse_reason"],
                    "output_path": str(output_path),
                    "status": "reused",
                }
                progress_log(
                    progress,
                    f"关键帧复用：{reference_image['reference_image_id']} <- {reused_reference_image_id}",
                    stage="step3",
                )
            else:
                source_assets = reference_image["source_assets"]
                source_materials = resolve_source_materials(source_assets, asset_lookup)
                reference_options = image_options.get("reference_images", {})
                reference_image_size = reference_options.get("size", "1024x1536")
                if video_aspect_ratio:
                    reference_image_size = image_size_for_aspect_ratio(video_aspect_ratio, fallback=reference_image_size)
                prompt = with_video_aspect_ratio(
                    reference_image["generation_prompt"],
                    video_aspect_ratio,
                    target="关键帧参考图",
                )
                payload = {
                    "reference_image_id": reference_image["reference_image_id"],
                    "prompt": prompt,
                    "output_path": str(output_path),
                    "source_materials": source_materials,
                    "source_assets": source_assets,
                    "size": reference_image_size,
                    "quality": reference_options.get("quality"),
                    "background": reference_options.get("background"),
                    "output_format": reference_options.get("output_format", "png"),
                    "skip_if_exists": skip_if_exists,
                }
                if video_aspect_ratio:
                    payload["aspect_ratio"] = video_aspect_ratio
                with progress_heartbeat(
                    progress,
                    f"关键帧仍在生成：{reference_image['reference_image_id']}",
                    stage="step3",
                ):
                    result = reference_provider.generate_image(
                        task_name="step3_reference_image",
                        prompt=prompt,
                        payload=payload,
                    )
                progress_log(
                    progress,
                    f"关键帧完成：{reference_image['reference_image_id']} -> {result['output_path']} ({result.get('status', 'unknown')})",
                    stage="step3",
                )
            reference_lookup[reference_image["reference_image_id"]] = result["output_path"]
            segment_result["reference_images"].append(result)
        generated_references.append(segment_result)

    result_payload = {
        "video_name": config.video_name(),
        "asset_images": generated_assets,
        "reference_image_plan": generated_references,
    }
    write_json(generation_output_path, result_payload)
    progress_log(progress, f"图片生成清单已写入 {generation_output_path}", stage="step3")

    return StageResult(
        stage_name="step3",
        output_path=str(generation_output_path),
        payload=result_payload,
    )


def build_asset_output_path(
    *,
    asset_output_dir: Path | None,
    subdir: str,
    name: str,
) -> Path:
    if asset_output_dir is None:
        raise ValueError("asset_output_dir cannot be None")
    return (asset_output_dir / subdir / f"{safe_filename(name)}.png").resolve()


def build_reference_output_path(
    *,
    reference_output_dir: Path | None,
    reference_image_id: str,
) -> Path:
    if reference_output_dir is None:
        raise ValueError("reference_output_dir cannot be None")
    return (reference_output_dir / f"{safe_filename(reference_image_id)}.png").resolve()


def resolve_source_materials(
    source_assets: dict[str, list[str]],
    asset_lookup: dict[str, dict[str, str]],
) -> list[str]:
    resolved: list[str] = []
    for name in source_assets.get("characters", []):
        resolved.append(resolve_asset_path(asset_lookup["characters"], "character", name))
    for name in source_assets.get("props", []):
        resolved.append(resolve_asset_path(asset_lookup["props"], "prop", name))
    for name in source_assets.get("scenes", []):
        resolved.append(resolve_asset_path(asset_lookup["scenes"], "scene", name))
    return resolved


def resolve_asset_path(lookup: dict[str, str], asset_type: str, name: str) -> str:
    if name not in lookup:
        raise ValueError(f"Missing generated {asset_type} asset: {name}")
    return lookup[name]


def with_video_aspect_ratio(prompt: str, video_aspect_ratio: str | None, *, target: str) -> str:
    if not video_aspect_ratio:
        return prompt
    ratio_line = f"目标视频画面比例：{video_aspect_ratio}；请按该比例组织{target}的画面构图。"
    if ratio_line in prompt:
        return prompt
    return f"{prompt.rstrip()}\n{ratio_line}"


def image_size_for_aspect_ratio(video_aspect_ratio: str | None, *, fallback: str) -> str:
    if not video_aspect_ratio:
        return fallback

    normalized = video_aspect_ratio.strip().lower().replace("：", ":")
    if normalized in {"16:9", "landscape"}:
        return "1536x1024"
    if normalized in {"9:16", "portrait"}:
        return "1024x1536"
    if normalized in {"1:1", "square"}:
        return "1024x1024"

    parts = normalized.split(":", maxsplit=1)
    if len(parts) != 2:
        return fallback
    try:
        width_ratio = float(parts[0])
        height_ratio = float(parts[1])
    except ValueError:
        return fallback

    if width_ratio > height_ratio:
        return "1536x1024"
    if width_ratio < height_ratio:
        return "1024x1536"
    return "1024x1024"


def copy_generated_reference(*, source_path: Path, target_path: Path) -> None:
    ensure_parent_dir(target_path)
    shutil.copyfile(source_path, target_path)
