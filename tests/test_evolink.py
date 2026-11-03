import json
import tempfile
import unittest
from pathlib import Path
import urllib.error

from app.core.evolink import EvolinkClient, EvolinkConfig, EvolinkError, EvolinkHTTPError


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class EvolinkClientTests(unittest.TestCase):
    def test_config_loads_env_file_without_overriding_explicit_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "EVOLINK_API_KEY=file-key\nEVOLINK_BASE_URL=https://file.example\n",
                encoding="utf-8",
            )

            config = EvolinkConfig.from_env(
                env_file,
                environ={"EVOLINK_API_KEY": "env-key", "EVOLINK_BASE_URL": "https://env.example/"},
            )

            self.assertEqual(config.api_key, "env-key")
            self.assertEqual(config.base_url, "https://env.example")

    def test_config_normalizes_versioned_base_url(self) -> None:
        config = EvolinkConfig.from_env(
            env_file=Path("missing.env"),
            environ={"EVOLINK_API_KEY": "key", "EVOLINK_BASE_URL": "https://api.evolink.ai/v1/"},
        )

        self.assertEqual(config.base_url, "https://api.evolink.ai")

    def test_config_from_values_normalizes_inputs(self) -> None:
        config = EvolinkConfig.from_values("  key  ", "https://api.example/v1/")

        self.assertEqual(config.api_key, "key")
        self.assertEqual(config.base_url, "https://api.example")

    def test_create_image_generation_encodes_local_image_as_data_url(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return _FakeResponse(b'{"id":"task-1","status":"processing"}')

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "input.png"
            image_path.write_bytes(b"png-bytes")
            client = EvolinkClient(
                EvolinkConfig(api_key="test-key", base_url="https://api.example"),
                transport=transport,
            )

            result = client.create_image_generation("make a frame", image_paths=[image_path])

        self.assertEqual(result["id"], "task-1")
        request = requests[0]
        self.assertEqual(request.full_url, "https://api.example/v1/images/generations")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertEqual(payload["prompt"], "make a frame")
        self.assertEqual(payload["size"], "16:9")
        self.assertEqual(payload["resolution"], "2K")
        self.assertEqual(payload["quality"], "medium")
        self.assertEqual(payload["image_urls"], ["data:image/png;base64,cG5nLWJ5dGVz"])

    def test_get_task_uses_generic_task_endpoint(self) -> None:
        seen = []

        def transport(request, timeout):
            seen.append(request.full_url)
            return _FakeResponse(b'{"id":"task-1","status":"completed","results":["https://file.example/out.png"]}')

        client = EvolinkClient(EvolinkConfig(api_key="test-key", base_url="https://api.example"), transport=transport)

        task = client.get_task("task-1")

        self.assertEqual(task["status"], "completed")
        self.assertEqual(seen, ["https://api.example/v1/tasks/task-1"])

    def test_create_vision_chat_completion_sends_image_content(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return _FakeResponse(b'{"choices":[{"message":{"content":"{\\"texts\\":[]}"}}]}')

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "input.png"
            image_path.write_bytes(b"png-bytes")
            client = EvolinkClient(
                EvolinkConfig(api_key="test-key", base_url="https://api.example"),
                transport=transport,
            )

            result = client.create_vision_chat_completion("extract text", image_paths=[image_path])

        self.assertEqual(result["choices"][0]["message"]["content"], '{"texts":[]}')
        request = requests[0]
        self.assertEqual(request.full_url, "https://api.example/v1/chat/completions")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-5.1")
        self.assertEqual(payload["messages"][0]["content"][0]["text"], "extract text")
        self.assertEqual(
            payload["messages"][0]["content"][1]["image_url"]["url"],
            "data:image/png;base64,cG5nLWJ5dGVz",
        )

    def test_connection_uses_models_endpoint_with_key(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return _FakeResponse(b'{"data":[]}')

        client = EvolinkClient(EvolinkConfig(api_key="test-key", base_url="https://api.example"), transport=transport)

        result = client.test_connection()

        self.assertEqual(result, {"data": []})
        self.assertEqual(requests[0].full_url, "https://api.example/v1/models")
        self.assertEqual(requests[0].get_method(), "GET")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-key")

    def test_download_first_result_writes_file_with_browser_user_agent(self) -> None:
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return _FakeResponse(b"image-data")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.png"
            client = EvolinkClient(EvolinkConfig(api_key="test-key"), transport=transport)

            written = client.download_first_result({"results": ["https://file.example/out.png"]}, target)

            self.assertEqual(written, target)
            self.assertEqual(target.read_bytes(), b"image-data")
            self.assertEqual(requests[0].headers["User-agent"], "Mozilla/5.0")

    def test_http_error_is_wrapped(self) -> None:
        def transport(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                hdrs=None,
                fp=_FakeResponse(b'{"error":{"message":"bad key"}}'),
            )

        client = EvolinkClient(EvolinkConfig(api_key="test-key"), transport=transport)

        with self.assertRaises(EvolinkHTTPError) as raised:
            client.get_task("task-1")

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("bad key", raised.exception.message)

    def test_missing_key_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EvolinkError):
                EvolinkConfig.from_env(Path(tmp) / "missing.env", environ={})


if __name__ == "__main__":
    unittest.main()
