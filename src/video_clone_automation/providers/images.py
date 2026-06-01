from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from video_clone_automation.providers.base import ImageProvider
from video_clone_automation.utils.files import ensure_parent_dir


class OpenAICompatibleImageProvider(ImageProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        model: str = "gpt-image-2",
        timeout_seconds: float = 600.0,
        size: str | None = None,
        quality: str | None = None,
        output_format: str = "png",
        background: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.size = size
        self.quality = quality
        self.output_format = output_format
        self.background = background

    def generate_image(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        output_path = Path(str(payload["output_path"])).resolve()
        if payload.get("skip_if_exists") and output_path.exists():
            result = {
                "task_name": task_name,
                "status": "existing",
                "output_path": str(output_path),
                "file_name": output_path.name,
                "prompt": payload.get("prompt") or prompt,
                "source_materials": payload.get("source_materials", []),
                "name": payload.get("name"),
                "reference_image_id": payload.get("reference_image_id"),
                "reused_reference_image_id": payload.get("reused_reference_image_id"),
                "category": payload.get("category"),
                "source_assets": payload.get("source_assets"),
            }
            if "aspect_ratio" in payload:
                result["aspect_ratio"] = payload.get("aspect_ratio")
            return result

        client = self._build_client()
        source_materials = payload.get("source_materials", [])
        request = self._build_request(prompt=payload.get("prompt") or prompt, payload=payload)

        if source_materials:
            with self._open_images(source_materials) as image_files:
                response = client.images.edit(image=image_files, **request)
        else:
            response = client.images.generate(**request)

        self._save_response_image(response=response, output_path=output_path)

        result = {
            "task_name": task_name,
            "status": "generated",
            "output_path": str(output_path),
            "file_name": output_path.name,
            "prompt": payload.get("prompt") or prompt,
            "source_materials": source_materials,
            "name": payload.get("name"),
            "reference_image_id": payload.get("reference_image_id"),
            "reused_reference_image_id": payload.get("reused_reference_image_id"),
            "category": payload.get("category"),
            "source_assets": payload.get("source_assets"),
            "image_size": request.get("size"),
            "image_quality": request.get("quality"),
        }
        if "aspect_ratio" in payload:
            result["aspect_ratio"] = payload.get("aspect_ratio")
        return result

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The `openai` package is required for the OpenAI-compatible image provider."
            ) from exc

        api_key = self.api_key or os.getenv(self.api_key_env)
        if not api_key:
            raise ValueError(f"Missing API key. Set {self.api_key_env} or configure api_key.")

        return OpenAI(
            base_url=self.base_url,
            api_key=api_key,
            timeout=self.timeout_seconds,
        )

    def _build_request(self, *, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": payload.get("model", self.model),
            "prompt": prompt,
        }
        size = payload.get("size", self.size)
        quality = payload.get("quality", self.quality)
        output_format = payload.get("output_format", self.output_format)
        background = payload.get("background", self.background)

        if size:
            request["size"] = size
        if quality:
            request["quality"] = quality
        if output_format:
            request["output_format"] = output_format
        if background:
            request["background"] = background
        return request

    def _save_response_image(self, *, response: Any, output_path: Path) -> None:
        image_data = response.data[0]
        b64_json = getattr(image_data, "b64_json", None)
        if not b64_json:
            raise ValueError("Image response does not contain b64_json data.")
        ensure_parent_dir(output_path)
        output_path.write_bytes(base64.b64decode(b64_json))

    class _open_images:
        def __init__(self, paths: list[str]) -> None:
            self.paths = paths
            self.handles: list[Any] = []

        def __enter__(self) -> list[Any]:
            self.handles = [open(path, "rb") for path in self.paths]
            return self.handles

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            for handle in self.handles:
                handle.close()
