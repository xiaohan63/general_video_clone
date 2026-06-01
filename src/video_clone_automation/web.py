from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from video_clone_automation.config import AppConfig, load_config
from video_clone_automation.utils.files import ensure_parent_dir, load_json
from video_clone_automation.utils.naming import safe_filename


REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = Path(__file__).resolve().parent / "web_assets"
CONFIG_ROOT = REPO_ROOT / "configs"
PROMPT_ROOT = REPO_ROOT / "prompts"
DATA_ROOT = REPO_ROOT / "data"
SRC_ROOT = REPO_ROOT / "src"

PROMPT_FIELDS = {
    "step1": "rewrite_prompt_path",
    "step2": "planning_prompt_path",
    "step3_asset": "asset_prompt_path",
    "step3_reference": "reference_prompt_path",
    "step4": "video_prompt_path",
}

PROVIDER_LABELS = {
    "script_rewrite": "Step 1 剧本仿写",
    "visual_planner": "Step 2 视觉规划",
    "asset_image": "Step 3 素材图",
    "reference_image": "Step 3 参考图",
    "video_segment": "Step 4 分幕视频",
}

JOBS: dict[str, dict[str, object]] = {}
JOBS_LOCK = threading.Lock()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the local pipeline web console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    print(f"Video Clone Web UI: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class WebHandler(BaseHTTPRequestHandler):
    server_version = "VideoCloneWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path == "/media":
            self.handle_media(parse_qs(parsed.query))
            return
        self.handle_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/save-config":
            self.handle_save_config()
            return
        if parsed.path == "/api/upload-video":
            self.handle_upload_video(parse_qs(parsed.query))
            return
        if parsed.path == "/api/run":
            self.handle_run_pipeline()
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("[web] " + format % args + "\n")

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/configs":
            self.send_json({"configs": list_configs()})
            return
        if path == "/api/config":
            config_path = first(query, "config")
            self.send_json(read_config_payload(config_path))
            return
        if path == "/api/results":
            config_path = first(query, "config")
            self.send_json(read_results_payload(config_path))
            return
        if path.startswith("/api/jobs/"):
            job_id = path.rsplit("/", maxsplit=1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if not job:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Job not found")
                return
            self.send_json(job)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def handle_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = ASSET_ROOT / "index.html"
        else:
            relative = path.lstrip("/")
            file_path = (ASSET_ROOT / relative).resolve()
            if not is_relative_to(file_path, ASSET_ROOT):
                self.send_error(HTTPStatus.FORBIDDEN)
                return

        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_media(self, query: dict[str, list[str]]) -> None:
        raw_path = first(query, "path")
        if not raw_path:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        path = safe_repo_path(unquote(raw_path))
        if path is None or not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def handle_save_config(self) -> None:
        try:
            payload = self.read_json_body()
            saved = save_config_from_payload(payload)
            self.send_json(saved)
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def handle_upload_video(self, query: dict[str, list[str]]) -> None:
        try:
            video_name = first(query, "video_name") or "uploaded"
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            file_name, file_bytes = parse_multipart_file(
                body=body,
                content_type=self.headers.get("Content-Type", ""),
                field_name="video",
            )
            extension = Path(file_name or "").suffix.lower() or ".mp4"
            if extension not in {".mp4", ".mov", ".m4v", ".webm"}:
                extension = ".mp4"
            relative_path = Path("data") / "input" / f"{safe_filename(video_name)}{extension}"
            target_path = (REPO_ROOT / relative_path).resolve()
            ensure_parent_dir(target_path)
            target_path.write_bytes(file_bytes)
            self.send_json(
                {
                    "input_video": relative_path.as_posix(),
                    "path": str(target_path),
                    "file_name": file_name,
                    "size": len(file_bytes),
                }
            )
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def handle_run_pipeline(self) -> None:
        try:
            payload = self.read_json_body()
            config_path = str(payload.get("config") or "")
            step = str(payload.get("step") or "all")
            resolved_config = safe_repo_path(config_path)
            if resolved_config is None or not resolved_config.exists():
                raise ValueError("Config path is invalid")
            if step not in {"step1", "step2", "step3", "step4", "step5", "all"}:
                raise ValueError("Step is invalid")

            job_id = uuid.uuid4().hex
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "id": job_id,
                    "status": "running",
                    "config": relative_to_repo(resolved_config),
                    "step": step,
                    "started_at": time.time(),
                    "returncode": None,
                    "lines": [],
                }
            thread = threading.Thread(
                target=run_pipeline_job,
                args=(job_id, resolved_config, step),
                daemon=True,
            )
            thread.start()
            self.send_json({"job_id": job_id})
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            return {}
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status=status)


def list_configs() -> list[dict[str, str]]:
    configs = []
    for path in sorted(CONFIG_ROOT.glob("pipeline.*.json")):
        try:
            config = load_config(str(path))
            video_name = config.video_name()
            aspect_ratio = config.video_aspect_ratio() or ""
        except Exception:
            video_name = path.stem.removeprefix("pipeline.")
            aspect_ratio = ""
        configs.append(
            {
                "path": relative_to_repo(path),
                "name": path.name,
                "video_name": video_name,
                "aspect_ratio": aspect_ratio,
            }
        )
    return configs


def read_config_payload(config_path: str | None) -> dict[str, object]:
    path = resolve_config_path(config_path)
    config = load_config(str(path))
    raw = config.raw

    providers = []
    for key, provider in raw.get("providers", {}).items():
        options = provider.get("options", {}) if isinstance(provider, dict) else {}
        providers.append(
            {
                "key": key,
                "label": PROVIDER_LABELS.get(key, key),
                "type": provider.get("type", "") if isinstance(provider, dict) else "",
                "model": options.get("model", ""),
            }
        )

    prompts = {}
    for prompt_key, field_name in PROMPT_FIELDS.items():
        step_name = "step3" if prompt_key.startswith("step3") else prompt_key
        prompt_path = raw.get("steps", {}).get(step_name, {}).get(field_name)
        prompts[prompt_key] = {
            "field": field_name,
            "path": prompt_path or "",
            "content": read_prompt_text(config, prompt_path),
        }

    return {
        "config_path": relative_to_repo(path),
        "raw": raw,
        "video_name": config.video_name(),
        "aspect_ratio": config.video_aspect_ratio() or "",
        "user_query": config.get("steps", "step1", "user_query", default=""),
        "input_video": config.get("steps", "step1", "input_video", default=""),
        "providers": providers,
        "prompts": prompts,
    }


def read_results_payload(config_path: str | None) -> dict[str, object]:
    path = resolve_config_path(config_path)
    config = load_config(str(path))
    video_dir = config.video_dir_name()
    intermediate_dir = (DATA_ROOT / "intermediate" / video_dir).resolve()
    output_dir = (DATA_ROOT / "output" / video_dir).resolve()

    step1_path = intermediate_dir / "step1_rewritten_script.json"
    step2_path = intermediate_dir / "step2_visual_plan.json"
    step3_path = intermediate_dir / "step3_generated_assets.json"
    step4_path = output_dir / "step4_video_segments.json"
    final_manifest_path = output_dir / "final_video_manifest.json"
    final_video_path = output_dir / "final_video.mp4"

    return {
        "video_name": config.video_name(),
        "aspect_ratio": config.video_aspect_ratio(),
        "paths": {
            "intermediate_dir": relative_to_repo(intermediate_dir),
            "output_dir": relative_to_repo(output_dir),
        },
        "script": read_json_file(step1_path),
        "visual_plan": read_json_file(step2_path),
        "generated_assets": normalize_asset_payload(read_json_file(step3_path)),
        "video_segments": normalize_video_segments(read_json_file(step4_path)),
        "final_manifest": read_json_file(final_manifest_path),
        "final_video": media_file_payload(final_video_path),
    }


def save_config_from_payload(payload: dict[str, object]) -> dict[str, object]:
    source_path = resolve_config_path(str(payload.get("source_config") or ""))
    source_config = load_config(str(source_path))
    raw = json.loads(json.dumps(source_config.raw, ensure_ascii=False))

    video_name = str(payload.get("video_name") or raw.get("video", {}).get("name") or source_config.video_name()).strip()
    if not video_name:
        raise ValueError("video_name is required")
    video_dir = safe_filename(video_name)
    aspect_ratio = str(payload.get("aspect_ratio") or "").strip()
    user_query = str(payload.get("user_query") or "")
    input_video = str(payload.get("input_video") or raw.get("steps", {}).get("step1", {}).get("input_video") or "")

    raw.setdefault("video", {})["name"] = video_name
    raw["video"]["aspect_ratio"] = aspect_ratio
    raw.setdefault("steps", {}).setdefault("step1", {})["user_query"] = user_query
    if input_video:
        raw["steps"]["step1"]["input_video"] = input_video

    models = payload.get("models") or {}
    if isinstance(models, dict):
        for provider_key, model in models.items():
            provider = raw.setdefault("providers", {}).get(provider_key)
            if isinstance(provider, dict):
                provider.setdefault("options", {})["model"] = str(model)

    prompts = payload.get("prompts") or {}
    if isinstance(prompts, dict):
        prompt_dir = PROMPT_ROOT / "web" / video_dir
        for prompt_key, prompt_content in prompts.items():
            if prompt_key not in PROMPT_FIELDS:
                continue
            prompt_file = prompt_dir / f"{prompt_key}.txt"
            ensure_parent_dir(prompt_file)
            prompt_file.write_text(str(prompt_content), encoding="utf-8")
            field_name = PROMPT_FIELDS[prompt_key]
            step_name = "step3" if str(prompt_key).startswith("step3") else str(prompt_key)
            raw.setdefault("steps", {}).setdefault(step_name, {})[field_name] = relative_to_repo(prompt_file)

    for step_config in raw.get("steps", {}).values():
        if isinstance(step_config, dict) and "skip_if_exists" in step_config and payload.get("force_regenerate"):
            step_config["skip_if_exists"] = False

    config_path = CONFIG_ROOT / f"pipeline.{video_dir}.json"
    config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "config_path": relative_to_repo(config_path),
        "video_name": video_name,
        "aspect_ratio": aspect_ratio,
        "input_video": input_video,
    }


def run_pipeline_job(job_id: str, config_path: Path, step: str) -> None:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(SRC_ROOT) if not existing_pythonpath else f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
    command = [
        sys.executable,
        "-m",
        "video_clone_automation.cli",
        "run",
        "--config",
        str(config_path),
        "--step",
        step,
    ]
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    with JOBS_LOCK:
        JOBS[job_id]["pid"] = process.pid
        JOBS[job_id]["command"] = " ".join(command)

    assert process.stdout is not None
    for line in process.stdout:
        with JOBS_LOCK:
            lines = JOBS[job_id].setdefault("lines", [])
            if isinstance(lines, list):
                lines.append(line.rstrip())
                del lines[:-400]

    returncode = process.wait()
    with JOBS_LOCK:
        JOBS[job_id]["returncode"] = returncode
        JOBS[job_id]["finished_at"] = time.time()
        JOBS[job_id]["status"] = "succeeded" if returncode == 0 else "failed"


def resolve_config_path(config_path: str | None) -> Path:
    if config_path:
        path = safe_repo_path(config_path)
        if path and path.exists() and path.suffix == ".json":
            return path
    configs = sorted(CONFIG_ROOT.glob("pipeline.*.json"))
    if not configs:
        raise FileNotFoundError("No pipeline config found")
    return configs[0].resolve()


def read_prompt_text(config: AppConfig, prompt_path: object) -> str:
    if not prompt_path:
        return ""
    resolved = config.resolve_path(str(prompt_path))
    if resolved and resolved.exists():
        return resolved.read_text(encoding="utf-8")
    return ""


def read_json_file(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return load_json(path)


def normalize_asset_payload(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not payload:
        return None
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    asset_images = payload.get("asset_images", {})
    if isinstance(asset_images, dict):
        for items in asset_images.values():
            if isinstance(items, list):
                for item in items:
                    add_media_url(item)
    for segment in payload.get("reference_image_plan", []):
        for item in segment.get("reference_images", []):
            add_media_url(item)
    return payload


def normalize_video_segments(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not payload:
        return None
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    for item in payload.get("segments", []):
        add_media_url(item)
    return payload


def media_file_payload(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return {
        "path": str(path),
        "media_url": media_url(path),
        "size": path.stat().st_size,
    }


def add_media_url(item: object) -> None:
    if not isinstance(item, dict):
        return
    output_path = item.get("output_path") or item.get("final_video_path") or item.get("assembled_video_path")
    if output_path:
        path = safe_repo_path(str(output_path))
        if path and path.exists():
            item["media_url"] = media_url(path)


def media_url(path: Path) -> str:
    return "/media?path=" + relative_to_repo(path)


def parse_multipart_file(*, body: bytes, content_type: str, field_name: str) -> tuple[str, bytes]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Missing multipart boundary")
    boundary = content_type.split(marker, maxsplit=1)[1].split(";", maxsplit=1)[0].strip().strip('"')
    delimiter = ("--" + boundary).encode("utf-8")
    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        header_bytes, file_bytes = part.split(b"\r\n\r\n", maxsplit=1)
        headers = header_bytes.decode("utf-8", errors="replace")
        if f'name="{field_name}"' not in headers:
            continue
        file_name = ""
        for item in headers.split(";"):
            item = item.strip()
            if item.startswith("filename="):
                file_name = item.split("=", maxsplit=1)[1].strip().strip('"')
                break
        if file_bytes.endswith(b"\r\n"):
            file_bytes = file_bytes[:-2]
        return file_name, file_bytes
    raise ValueError("Uploaded video field is missing")


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def safe_repo_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    return path if is_relative_to(path, REPO_ROOT) else None


def relative_to_repo(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
