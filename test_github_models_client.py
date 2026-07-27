import unittest

from github_models_client import configured_github_models, request_text


class FakeResponse:
    def __init__(self, status_code, body="", payload=None):
        self.status_code = status_code
        self.text = body
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class GitHubModelsClientTests(unittest.TestCase):
    def test_has_documented_openai_default(self):
        self.assertEqual(configured_github_models({})[0], "openai/gpt-4.1")

    def test_falls_back_between_models(self):
        calls = []

        def request(_url, **kwargs):
            model = kwargs["json"]["model"]
            calls.append(model)
            if model == "first":
                return FakeResponse(422, '{"message":"unsupported"}')
            return FakeResponse(
                200,
                payload={"choices": [{"message": {"content": "roteiro"}}]},
            )

        content, model = request_text(
            "token",
            "prompt",
            request,
            models=["first", "second"],
            sleep_func=lambda _delay: None,
        )

        self.assertEqual(content, "roteiro")
        self.assertEqual(model, "second")
        self.assertEqual(calls, ["first", "second"])

    def test_retries_transient_failure(self):
        calls = []

        def request(_url, **_kwargs):
            calls.append(True)
            if len(calls) == 1:
                return FakeResponse(429, '{"message":"rate limit"}')
            return FakeResponse(
                200,
                payload={"choices": [{"message": {"content": "ok"}}]},
            )

        content, _model = request_text(
            "token",
            "prompt",
            request,
            models=["model"],
            sleep_func=lambda _delay: None,
        )

        self.assertEqual(content, "ok")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
