from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import mimetypes
import os
from pathlib import Path
import time
from typing import Any, Callable
import urllib.error
import urllib.request


DEFAULT_ENV_FILE = Path(".key/.env_evolink_api_key")
DEFAULT_BASE_URL = "https://api.evolink.ai"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "16:9"
DEFAULT_RESOLUTION = "2K"
DEFAULT_QUALITY = "medium"
DEFAULT_VISION_MODEL = "gpt-5.1"


class EvolinkError(RuntimeError):
    pass


class EvolinkHTTPError(EvolinkError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Evolink API request failed with HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class EvolinkConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL

    @classmethod
    def from_values(cls, api_key: str, base_url: str = "") -> "EvolinkConfig":
        normalized_key = api_key.strip()
        if not normalized_key:
            raise EvolinkError("EVOLINK_API_KEY is not set.")
        return cls(api_key=normalized_key, base_url=_normalize_base_url(base_url or DEFAULT_BASE_URL))

    @classmethod
    def from_env(
        cls,
        env_file: Path | str = DEFAULT_ENV_FILE,
        environ: dict[str, str] | None = None,
    ) -> "EvolinkConfig":
        values = dict(os.environ if environ is None else environ)
        path = Path(env_file)
        if path.exists():
            values = {**_read_env_file(path), **values}

        api_key = values.get("EVOLINK_API_KEY", "").strip()
        if not api_key:
            raise EvolinkError("EVOLINK_API_KEY is not set.")
        base_url = _normalize_base_url(values.get("EVOLINK_BASE_URL", DEFAULT_BASE_URL))
        return cls(api_key=api_key, base_url=base_url)


Transport = Callable[[urllib.request.Request, float | None], Any]


class EvolinkClient:
    def __init__(
        self,
        config: EvolinkConfig | None = None,
        *,
        timeout: float = 60,
        transport: Transport | None = None,
    ) -> None:
        self.config = config or EvolinkConfig.from_env()
        self.timeout = timeout
        self._transport = transport or _urlopen_transport

    def create_image_generation(
        self,
        prompt: str,
        *,
        image_paths: list[Path] | None = None,
        image_urls: list[str] | None = None,
        size: str = DEFAULT_IMAGE_SIZE,
        resolution: str = DEFAULT_RESOLUTION,
        quality: str = DEFAULT_QUALITY,
        n: int = 1,
        model: str = DEFAULT_MODEL,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise EvolinkError("prompt must not be empty.")
        if n < 1 or n > 10:
            raise EvolinkError("n must be between 1 and 10.")

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "resolution": resolution,
            "quality": quality,
            "n": n,
        }
        urls = [*(image_urls or []), *(_image_path_to_data_url(path) for path in (image_paths or []))]
        if urls:
            payload["image_urls"] = urls
        if extra:
            payload = {**payload, **extra}

        return self._request_json("POST", "/v1/images/generations", payload)

    def create_vision_chat_completion(
        self,
        prompt: str,
        *,
        image_paths: list[Path],
        model: str = DEFAULT_VISION_MODEL,
        temperature: float = 0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise EvolinkError("prompt must not be empty.")
        if not image_paths:
            raise EvolinkError("at least one image is required for vision chat completion.")

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": _image_path_to_data_url(path)}}
            for path in image_paths
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return self._request_json("POST", "/v1/chat/completions", payload)

    def get_task(self, task_id: str) -> dict[str, Any]:
        if not task_id.strip():
            raise EvolinkError("task_id must not be empty.")
        return self._request_json("GET", f"/v1/tasks/{task_id}")

    def test_connection(self) -> dict[str, Any]:
        return self._request_json("GET", "/v1/models")

    def wait_for_task(
        self,
        task_id: str,
        *,
        poll_interval: float = 8,
        timeout: float = 600,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            task = self.get_task(task_id)
            status = task.get("status")
            if status == "completed":
                return task
            if status == "failed":
                raise EvolinkError(f"Evolink task failed: {json.dumps(task, ensure_ascii=False)}")
            if time.monotonic() >= deadline:
                raise TimeoutError(task_id)
            time.sleep(poll_interval)

    def download_first_result(self, task: dict[str, Any], output_path: Path | str) -> Path:
        results = task.get("results") or []
        if not results:
            raise EvolinkError("completed task does not contain a result URL.")
        return self.download_url(str(results[0]), output_path)

    def download_url(self, url: str, output_path: Path | str) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        try:
            with self._transport(request, 120) as response:
                target.write_bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise EvolinkHTTPError(exc.code, _read_error_body(exc)) from exc
        return target

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.config.base_url + path,
            data=data,
            headers={
                "Authorization": "Bearer " + self.config.api_key,
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method=method,
        )
        try:
            with self._transport(request, self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EvolinkHTTPError(exc.code, _read_error_body(exc)) from exc
        except json.JSONDecodeError as exc:
            raise EvolinkError("Evolink API returned invalid JSON.") from exc


def _urlopen_transport(request: urllib.request.Request, timeout: float | None) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.replace("export ", "", 1).strip()
        values[key] = value.strip().strip('"').strip("'")
    return values


def _normalize_base_url(value: str | None) -> str:
    base_url = (value or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
    if base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


def _image_path_to_data_url(path: Path) -> str:
    source = Path(path)
    if not source.exists():
        raise EvolinkError(f"image file does not exist: {source}")
    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:1000]
    except Exception:
        return str(exc)
