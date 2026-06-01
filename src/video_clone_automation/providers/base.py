from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    @abstractmethod
    def generate_json(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class ImageProvider(ABC):
    @abstractmethod
    def generate_image(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class VideoProvider(ABC):
    @abstractmethod
    def generate_video(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError
