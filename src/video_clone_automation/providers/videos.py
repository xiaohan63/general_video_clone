from __future__ import annotations

import base64
import json
import mimetypes
import os
import struct
import time
from pathlib import Path
from typing import Any

import httpx

from video_clone_automation.providers.base import VideoProvider
from video_clone_automation.utils.files import ensure_parent_dir, write_json
from video_clone_automation.utils.progress import progress_log


class OpenAICompatibleVideoProvider(VideoProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        model: str = "kling-omni-video",
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 10.0,
        max_wait_seconds: float = 1800.0,
        max_create_retries: int = 3,
        retry_delay_seconds: float = 60.0,
        endpoint_path: str = "/video/generations",
        image_input_mode: str = "data_url",
        payload_format: str = "openai_video",
        image_field: str = "image_urls",
        max_reference_images: int | None = 1,
        poll_style: str = "query",
        default_duration: int | None = None,
        default_aspect_ratio: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_wait_seconds = max_wait_seconds
        self.max_create_retries = max_create_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.endpoint_path = endpoint_path
        self.image_input_mode = image_input_mode
        self.payload_format = payload_format
        self.image_field = image_field
        self.max_reference_images = max_reference_images
        self.poll_style = poll_style
        self.default_duration = default_duration
        self.default_aspect_ratio = default_aspect_ratio

    def generate_video(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        progress = payload.get("progress")
        output_path = Path(str(payload["output_path"])).resolve()
        if payload.get("skip_if_exists") and output_path.exists() and self._can_use_existing_file(payload, output_path):
            progress_log(progress, f"复用已有视频文件：{output_path}", stage="video_api")
            return self._existing_result(task_name=task_name, payload=payload, output_path=output_path)

        task_payload = self._build_task_payload(prompt=payload.get("prompt") or prompt, payload=payload)
        task_output_path = output_path.with_suffix(".task.json")
        if payload.get("skip_if_exists") and task_output_path.exists():
            resumed_result = self._resume_existing_task(
                task_name=task_name,
                payload=payload,
                task_payload=task_payload,
                task_output_path=task_output_path,
                output_path=output_path,
                progress=progress,
            )
            if resumed_result:
                return resumed_result

        progress_log(progress, "提交视频生成任务", stage="video_api")
        create_response = self._post_generation(task_payload)
        immediate_video_url = self._maybe_extract_video_url(create_response)
        task_id = self._extract_task_id(create_response)
        progress_log(progress, f"视频任务已创建：task_id={task_id}", stage="video_api")
        write_json(task_output_path, {"request": self._safe_request(task_payload), "response": create_response})

        if immediate_video_url:
            final_response = create_response
            video_url = immediate_video_url
            progress_log(progress, "API 已直接返回视频地址，开始下载", stage="video_api")
        else:
            final_response = self._poll_generation(task_id, progress=progress)
            video_url = self._extract_video_url(final_response)
            progress_log(progress, "轮询完成，开始下载视频", stage="video_api")
        self._download_video(video_url=video_url, output_path=output_path)
        progress_log(progress, f"视频下载完成：{output_path}", stage="video_api")

        write_json(
            output_path.with_suffix(".json"),
            {
                "task_name": task_name,
                "task_id": task_id,
                "request": self._safe_request(task_payload),
                "create_response": create_response,
                "final_response": final_response,
                "output_path": str(output_path),
                "video_url": video_url,
            },
        )

        return {
            "task_name": task_name,
            "status": "generated",
            "task_id": task_id,
            "segment_id": payload.get("segment_id"),
            "output_path": str(output_path),
            "video_url": video_url,
            "duration": payload.get("duration", self.default_duration),
            "reference_image_paths": payload.get("reference_image_paths", []),
            "aspect_ratio": payload.get("aspect_ratio", self.default_aspect_ratio),
            "prompt": payload.get("prompt") or prompt,
        }

    def _resume_existing_task(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        task_payload: dict[str, Any],
        task_output_path: Path,
        output_path: Path,
        progress: object | None = None,
    ) -> dict[str, Any] | None:
        try:
            task_metadata = json.loads(task_output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        create_response = task_metadata.get("response")
        if not isinstance(create_response, dict):
            return None

        try:
            task_id = self._extract_task_id(create_response)
        except ValueError:
            return None

        progress_log(progress, f"恢复已有视频任务：task_id={task_id}", stage="video_api")
        try:
            immediate_video_url = self._maybe_extract_video_url(create_response)
            if immediate_video_url:
                final_response = create_response
                video_url = immediate_video_url
            else:
                final_response = self._poll_generation(task_id, progress=progress)
                video_url = self._extract_video_url(final_response)
        except Exception as exc:
            progress_log(
                progress,
                f"已有视频任务不可继续，将重新提交：task_id={task_id}，原因={exc}",
                stage="video_api",
            )
            return None

        progress_log(progress, "恢复任务已完成，开始下载视频", stage="video_api")
        self._download_video(video_url=video_url, output_path=output_path)
        progress_log(progress, f"视频下载完成：{output_path}", stage="video_api")

        write_json(
            output_path.with_suffix(".json"),
            {
                "task_name": task_name,
                "task_id": task_id,
                "request": task_metadata.get("request") or self._safe_request(task_payload),
                "create_response": create_response,
                "final_response": final_response,
                "output_path": str(output_path),
                "video_url": video_url,
            },
        )

        return {
            "task_name": task_name,
            "status": "generated",
            "task_id": task_id,
            "segment_id": payload.get("segment_id"),
            "output_path": str(output_path),
            "video_url": video_url,
            "duration": payload.get("duration", self.default_duration),
            "reference_image_paths": payload.get("reference_image_paths", []),
            "aspect_ratio": payload.get("aspect_ratio", self.default_aspect_ratio),
            "prompt": payload.get("prompt"),
        }

    def _existing_result(
        self,
        *,
        task_name: str,
        payload: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        return {
            "task_name": task_name,
            "status": "existing",
            "segment_id": payload.get("segment_id"),
            "output_path": str(output_path),
            "duration": payload.get("duration", self.default_duration),
            "reference_image_paths": payload.get("reference_image_paths", []),
            "aspect_ratio": payload.get("aspect_ratio", self.default_aspect_ratio),
            "prompt": payload.get("prompt"),
        }

    def _build_task_payload(self, *, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "prompt": prompt,
        }
        if self.payload_format == "kling_omni":
            request["model_name"] = payload.get("model", self.model)
        else:
            request["model"] = payload.get("model", self.model)

        reference_image_paths = payload.get("reference_image_paths", [])
        if self.max_reference_images is not None:
            reference_image_paths = reference_image_paths[: self.max_reference_images]
        if reference_image_paths:
            image_inputs = [self._image_to_input(path) for path in reference_image_paths]
            if self.payload_format == "kling_omni":
                request["image_list"] = [
                    {"image_id": index, "image_url": image_input}
                    for index, image_input in enumerate(image_inputs, start=1)
                ]
                request["prompt"] = self._prefix_image_markers(prompt, len(image_inputs))
            elif self.image_field == "image_urls":
                request["image_urls"] = image_inputs
                request["prompt"] = self._prefix_image_markers(prompt, len(image_inputs))
            elif self.image_field == "image_list":
                request["image_list"] = [{"image_url": image_input} for image_input in image_inputs]
            else:
                request[self.image_field] = image_inputs

        duration = payload.get("duration", self.default_duration)
        if duration is not None:
            request["duration"] = duration

        aspect_ratio = payload.get("aspect_ratio", self.default_aspect_ratio)
        if aspect_ratio:
            request["aspect_ratio"] = aspect_ratio

        if self.payload_format == "kling_omni":
            sound = payload.get("sound")
            if sound is None and payload.get("audio") is not None:
                sound = payload.get("audio")
            if sound is not None:
                request["sound"] = self._normalize_sound(sound)
        elif payload.get("audio") is not None:
            request["audio"] = payload.get("audio")

        extra_body = payload.get("extra_body", {})
        if extra_body:
            request.update(extra_body)

        return request

    @staticmethod
    def _normalize_sound(value: Any) -> str:
        if isinstance(value, bool):
            return "on" if value else "off"
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return "on"
        if text in {"false", "0", "no", "off"}:
            return "off"
        return str(value)

    def _can_use_existing_file(self, payload: dict[str, Any], output_path: Path) -> bool:
        if not self._existing_duration_matches(payload, output_path):
            return False
        if not self._sound_requested(payload):
            return True
        return self._file_has_audio_track(output_path)

    def _existing_duration_matches(self, payload: dict[str, Any], output_path: Path) -> bool:
        requested_duration = payload.get("duration", self.default_duration)
        if requested_duration is None:
            return True

        metadata_path = output_path.with_suffix(".json")
        if not metadata_path.exists():
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        request = metadata.get("request")
        if not isinstance(request, dict) or request.get("duration") is None:
            return False
        return self._duration_values_equal(requested_duration, request.get("duration"))

    @staticmethod
    def _duration_values_equal(left: Any, right: Any) -> bool:
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return str(left) == str(right)

    def _sound_requested(self, payload: dict[str, Any]) -> bool:
        sound = payload.get("sound")
        if sound is None:
            sound = payload.get("audio")
        extra_body = payload.get("extra_body", {})
        if isinstance(extra_body, dict):
            if extra_body.get("sound") is not None:
                sound = extra_body.get("sound")
            elif extra_body.get("audio") is not None:
                sound = extra_body.get("audio")
        if sound is None:
            return False
        return self._normalize_sound(sound) == "on"

    @staticmethod
    def _file_has_audio_track(path: Path) -> bool:
        data = path.read_bytes()
        end = len(data)
        stack: list[tuple[int, int]] = [(0, end)]
        containers = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta", b"meta"}

        while stack:
            pos, box_end = stack.pop()
            while pos + 8 <= box_end:
                size = struct.unpack(">I", data[pos : pos + 4])[0]
                box_type = data[pos + 4 : pos + 8]
                header_size = 8
                if size == 1:
                    if pos + 16 > box_end:
                        break
                    size = struct.unpack(">Q", data[pos + 8 : pos + 16])[0]
                    header_size = 16
                elif size == 0:
                    size = box_end - pos
                if size < header_size or pos + size > box_end:
                    break

                if box_type == b"hdlr":
                    payload = data[pos + header_size : pos + size]
                    if len(payload) >= 12 and payload[8:12] == b"soun":
                        return True
                if box_type in containers:
                    child_start = pos + header_size + (4 if box_type == b"meta" else 0)
                    stack.append((child_start, pos + size))
                pos += size

        return False

    def _post_generation(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_create_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self._generation_url(),
                        headers=self._headers(),
                        json=payload,
                    )
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_create_retries:
                    time.sleep(self.retry_delay_seconds)
                    continue
                raise RuntimeError(
                    "Video generation request failed after "
                    f"{self.max_create_retries} attempt(s) at {self._generation_url()}: {exc}. "
                    "请检查网络/DNS、代理设置和视频 API 服务状态。"
                ) from exc
            if response.status_code == 429 and attempt < self.max_create_retries:
                time.sleep(self.retry_delay_seconds)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                raise RuntimeError(
                    f"Video generation request failed with HTTP {response.status_code}: "
                    f"{response.text[:1000]}"
                ) from exc
            return response.json()
        if last_error:
            raise RuntimeError(f"Video generation request failed: {last_error}") from last_error
        raise RuntimeError("Video generation request failed before receiving a response.")

    def _poll_generation(self, task_id: str, *, progress: object | None = None) -> dict[str, Any]:
        started_at = time.monotonic()
        attempt = 0
        while True:
            attempt += 1
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    if self.poll_style == "path":
                        response = client.get(
                            f"{self._generation_url()}/{task_id}",
                            headers=self._headers(),
                        )
                    else:
                        response = client.get(
                            self._generation_url(),
                            headers=self._headers(),
                            params={"task_id": task_id},
                        )
                    response.raise_for_status()
                    payload = response.json()
            except httpx.RequestError as exc:
                raise RuntimeError(
                    f"Video generation polling failed for task {task_id}: {exc}"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    "Video generation polling failed "
                    f"for task {task_id} with HTTP {exc.response.status_code}: "
                    f"{exc.response.text[:1000]}"
                ) from exc

            elapsed = int(time.monotonic() - started_at)
            status = self._status(payload) or "unknown"
            progress_log(
                progress,
                f"轮询第 {attempt} 次：task_id={task_id}，status={status}，已等待 {elapsed}s",
                stage="video_api",
            )

            if self._is_terminal_success(payload):
                return payload
            if self._is_terminal_failure(payload):
                raise RuntimeError(f"Video generation failed for task {task_id}: {payload}")
            if time.monotonic() - started_at > self.max_wait_seconds:
                raise TimeoutError(f"Timed out waiting for video generation task {task_id}")
            time.sleep(self.poll_interval_seconds)

    def _download_video(self, *, video_url: str, output_path: Path) -> None:
        ensure_parent_dir(output_path)
        try:
            with httpx.stream("GET", video_url, timeout=self.timeout_seconds) as response:
                response.raise_for_status()
                with output_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except httpx.RequestError as exc:
            raise RuntimeError(f"Video download failed from {video_url}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Video download failed with HTTP {exc.response.status_code}: {exc.response.text[:1000]}"
            ) from exc

    def _generation_url(self) -> str:
        return f"{self.base_url}{self.endpoint_path}"

    def _headers(self) -> dict[str, str]:
        api_key = self.api_key or os.getenv(self.api_key_env)
        if not api_key:
            raise ValueError(f"Missing API key. Set {self.api_key_env} or configure api_key.")
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _image_to_input(self, path: str) -> str:
        if self.image_input_mode not in {"data_url", "base64"}:
            return path
        image_path = Path(path).resolve()
        mime_type, _ = mimetypes.guess_type(image_path.name)
        if not mime_type:
            mime_type = "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        if self.image_input_mode == "base64":
            return encoded
        return f"data:{mime_type};base64,{encoded}"

    def _prefix_image_markers(self, prompt: str, image_count: int) -> str:
        markers = " ".join(f"<<<image_{index}>>>" for index in range(1, image_count + 1))
        return f"{markers}\n\n{prompt}" if markers else prompt

    def _extract_task_id(self, payload: dict[str, Any]) -> str:
        candidates = [
            payload.get("task_id"),
            payload.get("id"),
            payload.get("data", {}).get("task_id") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("id") if isinstance(payload.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if candidate:
                return str(candidate)
        raise ValueError(f"Unable to find task id in response: {payload}")

    def _extract_video_url(self, payload: dict[str, Any]) -> str:
        video_url = self._maybe_extract_video_url(payload)
        if video_url:
            return video_url
        raise ValueError(f"Unable to find video url in response: {payload}")

    def _maybe_extract_video_url(self, payload: dict[str, Any]) -> str | None:
        candidates = [
            payload.get("video_url"),
            payload.get("url"),
            payload.get("data", {}).get("video_url") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("url") if isinstance(payload.get("data"), dict) else None,
        ]

        task_result = payload.get("task_result") or payload.get("data", {}).get("task_result", {})
        if isinstance(task_result, dict):
            videos = task_result.get("videos") or task_result.get("video") or []
            if isinstance(videos, list) and videos:
                first = videos[0]
                if isinstance(first, dict):
                    candidates.extend([first.get("url"), first.get("video_url")])
                elif isinstance(first, str):
                    candidates.append(first)

        for candidate in candidates:
            if candidate:
                return str(candidate)
        return None

    def _is_terminal_success(self, payload: dict[str, Any]) -> bool:
        if self._maybe_extract_video_url(payload):
            return True
        status = self._status(payload)
        return status in {"succeeded", "succeed", "success", "completed", "complete", "finished"}

    def _is_terminal_failure(self, payload: dict[str, Any]) -> bool:
        status = self._status(payload)
        return status in {"failed", "failure", "error", "cancelled", "canceled"}

    def _status(self, payload: dict[str, Any]) -> str:
        candidates = [
            payload.get("status"),
            payload.get("task_status"),
            payload.get("data", {}).get("status") if isinstance(payload.get("data"), dict) else None,
            payload.get("data", {}).get("task_status") if isinstance(payload.get("data"), dict) else None,
        ]
        for candidate in candidates:
            if candidate:
                return str(candidate).lower()
        return ""

    def _safe_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe_payload = dict(payload)
        image_list = safe_payload.get("image_list")
        if isinstance(image_list, list):
            safe_payload["image_list"] = [
                {
                    **item,
                    "image_url": self._redact_data_url(str(item.get("image_url", ""))),
                }
                if isinstance(item, dict)
                else item
                for item in image_list
            ]
        image_urls = safe_payload.get("image_urls")
        if isinstance(image_urls, list):
            safe_payload["image_urls"] = [
                self._redact_data_url(str(image_url)) for image_url in image_urls
            ]
        return safe_payload

    def _redact_data_url(self, value: str) -> str:
        if value.startswith("data:"):
            prefix = value.split(",", 1)[0]
            return f"{prefix},<base64 omitted>"
        if len(value) > 200:
            return f"{value[:80]}...<base64 omitted>...{value[-20:]}"
        return value
