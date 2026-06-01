from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx

from video_clone_automation.providers.base import LLMProvider


STEP1_REQUIRED_KEYS = {
    "storyline",
    "storyline_rationale",
    "overall_style",
    "character_design",
    "prop_design",
    "scene_design",
    "script_breakdown",
}


def parse_json_object_content(*, content: str, task_name: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = strip_code_fence(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = extract_best_json_object(text, task_name=task_name)

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object for {task_name}, got {type(parsed).__name__}")
    return parsed


def extract_best_json_object(text: str, *, task_name: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append((end, parsed))

    if candidates:
        required_keys = STEP1_REQUIRED_KEYS if task_name == "step1_rewrite" else set()
        for _, candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
            if not required_keys or required_keys.issubset(candidate):
                return candidate
        return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]

    preview = text[:300]
    raise ValueError(
        f"Model output for {task_name} is not valid JSON. Raw content preview: {preview}"
    )


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3:
        return "\n".join(lines[1:-1]).strip()
    return stripped.strip("`").strip()


class OpenAICompatibleChatProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str | None = None,
        api_key_env: str = "OPENROUTER_API_KEY",
        model: str = "google/gemini-3.1-pro-preview",
        reasoning_enabled: bool = True,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float = 600.0,
        http_referer: str | None = None,
        x_title: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.model = model
        self.reasoning_enabled = reasoning_enabled
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.http_referer = http_referer
        self.x_title = x_title

    def generate_json(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._build_client()
        messages = payload.get("messages") or self._build_default_messages(
            prompt=prompt,
            payload=payload,
        )
        request = self._build_request(messages=messages, payload=payload)
        response = self._create_chat_completion(client=client, request=request)
        assistant_message = response.choices[0].message

        for follow_up_message in payload.get("follow_up_messages", []):
            messages = [
                *messages,
                self._assistant_message_for_follow_up(assistant_message),
                {"role": "user", "content": follow_up_message},
            ]
            request["messages"] = messages
            response = self._create_chat_completion(client=client, request=request)
            assistant_message = response.choices[0].message

        content = self._extract_text_content(assistant_message.content)
        return self._parse_json_content(content=content, task_name=task_name)

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The `openai` package is required for the OpenAI-compatible provider. "
                "Install project dependencies first."
            ) from exc

        api_key = self.api_key or os.getenv(self.api_key_env)
        if not api_key:
            raise ValueError(
                f"Missing API key. Set {self.api_key_env} or configure api_key."
            )

        return OpenAI(
            base_url=self.base_url,
            api_key=api_key,
            timeout=self.timeout_seconds,
        )

    def _build_request(
        self,
        *,
        messages: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": payload.get("model", self.model),
            "messages": messages,
        }

        temperature = payload.get("temperature", self.temperature)
        if temperature is not None:
            request["temperature"] = temperature

        max_tokens = payload.get("max_tokens", self.max_tokens)
        if max_tokens is not None:
            request["max_tokens"] = max_tokens

        response_format = payload.get("response_format")
        if response_format:
            request["response_format"] = response_format

        extra_headers = self._build_extra_headers(payload)
        if extra_headers:
            request["extra_headers"] = extra_headers

        extra_body = dict(payload.get("extra_body", {}))
        reasoning_enabled = payload.get("reasoning_enabled", self.reasoning_enabled)
        if reasoning_enabled:
            extra_body["reasoning"] = {"enabled": True}
        if extra_body:
            request["extra_body"] = extra_body

        return request

    def _create_chat_completion(
        self,
        *,
        client: Any,
        request: dict[str, Any],
    ) -> Any:
        try:
            return client.chat.completions.create(**request)
        except Exception:
            if request.get("response_format"):
                fallback_request = dict(request)
                fallback_request.pop("response_format", None)
                return client.chat.completions.create(**fallback_request)
            raise

    def _build_extra_headers(self, payload: dict[str, Any]) -> dict[str, str]:
        headers: dict[str, str] = {}
        http_referer = payload.get("http_referer", self.http_referer)
        x_title = payload.get("x_title", self.x_title)
        if http_referer:
            headers["HTTP-Referer"] = http_referer
        if x_title:
            headers["X-Title"] = x_title
        return headers

    def _build_default_messages(
        self,
        *,
        prompt: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        system_message = {"role": "system", "content": prompt}
        input_text = str(payload.get("input_text", "")).strip()
        input_video = payload.get("input_video")

        if input_video:
            user_content: list[dict[str, Any]] = []
            if input_text:
                user_content.append({"type": "text", "text": input_text})
            user_content.append(
                {
                    "type": "video_url",
                    "video_url": {"url": self._normalize_video_input(str(input_video))},
                }
            )
            return [system_message, {"role": "user", "content": user_content}]

        return [system_message, {"role": "user", "content": input_text}]

    def _normalize_video_input(self, input_video: str) -> str:
        if input_video.startswith(("http://", "https://", "data:video/")):
            return input_video

        video_path = Path(input_video).expanduser().resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        mime_type, _ = mimetypes.guess_type(video_path.name)
        if not mime_type or not mime_type.startswith("video/"):
            mime_type = "video/mp4"

        encoded = base64.b64encode(video_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _assistant_message_for_follow_up(self, assistant_message: Any) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": self._extract_text_content(assistant_message.content),
        }
        reasoning_details = getattr(assistant_message, "reasoning_details", None)
        if reasoning_details:
            message["reasoning_details"] = reasoning_details
        return message

    def _extract_text_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    parts.append(str(item.get("text", "")))
            return "\n".join(part for part in parts if part).strip()
        return str(content)

    def _parse_json_content(self, *, content: str, task_name: str) -> dict[str, Any]:
        return parse_json_object_content(content=content, task_name=task_name)

    def _strip_code_fence(self, text: str) -> str:
        return strip_code_fence(text)


class OpenRouterChatProvider(OpenAICompatibleChatProvider):
    pass


class YunwuGeminiGenerateContentProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str = "https://yunwu.ai/v1beta",
        api_key: str | None = None,
        api_key_env: str = "YUNWU_API_KEY",
        model: str = "gemini-3.1-pro-preview",
        timeout_seconds: float = 1800.0,
        temperature: float | None = None,
        top_p: float | None = None,
        response_mime_type: str | None = "application/json",
        include_thoughts: bool | None = None,
        thinking_budget: int | None = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 3.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.top_p = top_p
        self.response_mime_type = response_mime_type
        self.include_thoughts = include_thoughts
        self.thinking_budget = thinking_budget
        self.max_retries = max(1, max_retries)
        self.retry_delay_seconds = retry_delay_seconds

    def generate_json(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        request_payload = self._build_generate_content_payload(prompt=prompt, payload=payload)
        response_payload = self._post_generate_content(request_payload)
        content = self._extract_text_content(response_payload)
        return self._parse_json_content(content=content, task_name=task_name)

    def _build_generate_content_payload(
        self,
        *,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        input_text = str(payload.get("input_text", "")).strip()
        parts: list[dict[str, Any]] = []
        input_video = payload.get("input_video")
        if input_video:
            parts.append(self._build_inline_video_part(str(input_video)))
        if input_text:
            parts.append({"text": input_text})

        request_payload: dict[str, Any] = {
            "systemInstruction": {
                "parts": [{"text": prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": parts or [{"text": input_text}],
                }
            ],
        }

        generation_config = self._build_generation_config(payload)
        if generation_config:
            request_payload["generationConfig"] = generation_config
        return request_payload

    def _build_generation_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        generation_config: dict[str, Any] = {}
        temperature = payload.get("temperature", self.temperature)
        if temperature is not None:
            generation_config["temperature"] = temperature
        top_p = payload.get("top_p", self.top_p)
        if top_p is not None:
            generation_config["topP"] = top_p
        response_mime_type = payload.get("response_mime_type", self.response_mime_type)
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type

        include_thoughts = payload.get("include_thoughts", self.include_thoughts)
        thinking_budget = payload.get("thinking_budget", self.thinking_budget)
        thinking_config: dict[str, Any] = {}
        if include_thoughts is not None:
            thinking_config["includeThoughts"] = include_thoughts
        if thinking_budget is not None:
            thinking_config["thinkingBudget"] = thinking_budget
        if thinking_config:
            generation_config["thinkingConfig"] = thinking_config
        return generation_config

    def _build_inline_video_part(self, input_video: str) -> dict[str, Any]:
        video_path = Path(input_video).expanduser().resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        mime_type, _ = mimetypes.guess_type(video_path.name)
        if not mime_type or not mime_type.startswith("video/"):
            mime_type = "video/mp4"

        encoded = base64.b64encode(video_path.read_bytes()).decode("ascii")
        return {
            "inlineData": {
                "mimeType": mime_type,
                "data": encoded,
            }
        }

    def _post_generate_content(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        api_key = self.api_key or os.getenv(self.api_key_env)
        if not api_key:
            raise ValueError(
                f"Missing API key. Set {self.api_key_env} or configure api_key."
            )

        endpoint = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(endpoint, headers=headers, json=request_payload)
                if (
                    response.status_code == 429 or 500 <= response.status_code < 600
                ) and attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds)
                    continue
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    "Yunwu Gemini generateContent request failed "
                    f"with HTTP {exc.response.status_code} at {endpoint}: "
                    f"{exc.response.text[:1000]}"
                ) from exc
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds)
                    continue
                raise RuntimeError(
                    "Yunwu Gemini generateContent request failed after "
                    f"{self.max_retries} attempt(s) at {endpoint}: {exc}. "
                    f"请检查网络/DNS、代理设置，以及 {self.api_key_env} 是否可用。"
                ) from exc
        else:
            raise RuntimeError(
                f"Yunwu Gemini generateContent request failed before receiving a response: {last_error}"
            )
        if not isinstance(payload, dict):
            raise ValueError(f"Expected Gemini response object, got {type(payload).__name__}")
        return payload

    def _extract_text_content(self, response_payload: dict[str, Any]) -> str:
        candidates = response_payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"Gemini response has no candidates: {response_payload}")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not isinstance(parts, list):
            raise ValueError(f"Gemini response content.parts is not a list: {response_payload}")

        texts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("text")
        ]
        content = "\n".join(texts).strip()
        if not content:
            raise ValueError(f"Gemini response has no text content: {response_payload}")
        return content

    def _parse_json_content(self, *, content: str, task_name: str) -> dict[str, Any]:
        return parse_json_object_content(content=content, task_name=task_name)
