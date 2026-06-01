from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_clone_automation.utils.naming import safe_filename


class AppConfig:
    def __init__(self, raw: dict[str, Any], source_path: Path) -> None:
        self.raw = raw
        self.source_path = source_path.resolve()
        self.config_dir = self.source_path.parent.resolve()
        workspace_root = self.get("paths", "workspace_root", default=".")
        self.root_dir = (self.config_dir / workspace_root).resolve()

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self.raw
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def resolve_path(self, value: str | None) -> Path | None:
        if value is None:
            return None
        value = self.expand_path_template(value)
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()

    def resolve_step_path(self, step_name: str, field_name: str) -> Path:
        value = self.get("steps", step_name, field_name)
        if not value:
            raise ValueError(f"Missing config field: steps.{step_name}.{field_name}")
        if step_name == "step1" and field_name == "input_video":
            path = self.resolve_input_video_path(str(value))
            if path is None:
                raise ValueError(f"Invalid path field: steps.{step_name}.{field_name}")
            return path
        path = self.resolve_path(str(value))
        if path is None:
            raise ValueError(f"Invalid path field: steps.{step_name}.{field_name}")
        return path

    def step_enabled(self, step_name: str) -> bool:
        return bool(self.get("steps", step_name, "enabled", default=True))

    def provider_config(self, name: str) -> dict[str, Any]:
        config = self.get("providers", name, default={})
        if not isinstance(config, dict):
            raise ValueError(f"Provider config for {name} must be an object")
        return config

    def video_aspect_ratio(self) -> str | None:
        value = self.get("video", "aspect_ratio")
        if value is None:
            value = self.get("steps", "step4", "video_options", "aspect_ratio")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def video_name(self) -> str:
        value = self.config_file_video_name()
        if value is None:
            value = self.get("video", "name")
        if value is None:
            value = self.get("project", "name", default="default")
        return str(value).strip() or "default"

    def video_dir_name(self) -> str:
        return safe_filename(self.video_name())

    def config_file_video_name(self) -> str | None:
        name = self.source_path.name
        prefix = "pipeline."
        suffix = ".json"
        if not name.startswith(prefix) or not name.endswith(suffix):
            return None

        value = name[len(prefix):-len(suffix)].strip()
        if not value or "." in value:
            return None
        return value

    def resolve_input_video_path(self, value: str) -> Path | None:
        configured_path = self.resolve_path(value)
        config_file_video_name = self.config_file_video_name()
        if not config_file_video_name:
            return configured_path

        configured_video_name = self.get("video", "name")
        if str(configured_video_name or "").strip() == config_file_video_name:
            return configured_path

        inferred_path = (self.root_dir / "data" / "input" / f"{self.video_dir_name()}.mp4").resolve()
        if inferred_path.exists():
            return inferred_path
        return configured_path

    def expand_path_template(self, value: str) -> str:
        replacements = {
            "{video_name}": self.video_dir_name(),
            "{project_name}": safe_filename(str(self.get("project", "name", default="default"))),
        }
        expanded = value
        for token, replacement in replacements.items():
            expanded = expanded.replace(token, replacement)
        return expanded


def load_config(config_path: str) -> AppConfig:
    path = Path(config_path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig(raw=raw, source_path=path)
