import unittest

from gemini_client import configured_models, request_with_fallback


class FakeResponse:
    def __init__(self, status_code, body="", payload=None, headers=None):
        self.status_code = status_code
        self.text = body
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class GeminiClientTests(unittest.TestCase):
    def test_uses_stable_default_models(self):
        self.assertEqual(
            configured_models({}),
            [
                "gemini-3.6-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ],
        )

    def test_deduplicates_configured_models(self):
        self.assertEqual(
            configured_models({"GEMINI_MODELS": "one, two, one"}),
            ["one", "two"],
        )

    def test_falls_back_after_repeated_429(self):
        calls = []
        sleeps = []

        def request(url, **_kwargs):
            calls.append(url)
            if "primary" in url:
                return FakeResponse(
                    429,
                    '{"error":{"message":"quota"}}',
                    headers={"Retry-After": "3"},
                )
            return FakeResponse(200, payload={"ok": True})

        result, model = request_with_fallback(
            "secret",
            {"contents": []},
            request,
            models=["primary", "fallback"],
            sleep_func=sleeps.append,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(model, "fallback")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [3])

    def test_does_not_retry_non_transient_error_on_same_model(self):
        calls = []

        def request(url, **_kwargs):
            calls.append(url)
            if "primary" in url:
                return FakeResponse(400, '{"error":{"message":"invalid"}}')
            return FakeResponse(200, payload={"ok": True})

        _result, model = request_with_fallback(
            "secret",
            {},
            request,
            models=["primary", "fallback"],
            sleep_func=lambda _delay: None,
        )

        self.assertEqual(model, "fallback")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
