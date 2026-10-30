"""Tests for the LLM adapters against recorded/representative provider streams.

Run inside the backend container:
    cd /app && python -m unittest src.tests.test_llm_provider -v
"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["LAIUNI_DATA_DIR"] = _TMP.name

import httpx  # noqa: E402

from src.services import llm_provider as lp  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def _run(coro):
    return asyncio.run(coro)  # fresh loop: other tests may leave none set


class _FixtureTransport:
    """Patches httpx.AsyncClient in llm_provider to replay a fixture and record the request."""

    def __init__(self, fixture: str, status: int = 200):
        self.body = (FIXTURES / fixture).read_bytes() if fixture else b""
        self.status = status
        self.requests: list[httpx.Request] = []

    def __enter__(self):
        self._orig = lp.httpx.AsyncClient
        real = self._orig

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, content=self.body,
                                  headers={"content-type": "text/event-stream"})

        def factory(*a, **kw):
            kw.pop("transport", None)
            return real(*a, transport=httpx.MockTransport(handler), **kw)

        lp.httpx.AsyncClient = factory
        return self

    def __exit__(self, *a):
        lp.httpx.AsyncClient = self._orig


async def _collect(adapter, conn, model, **kw):
    out = []
    async for tok in adapter.stream(conn, model, [{"role": "user", "content": "hi"}],
                                    kw.get("temperature"), kw.get("max_tokens"), kw.get("num_ctx")):
        out.append(tok)
    return out


class ContentNormaliserTest(unittest.TestCase):
    def test_string(self):
        self.assertEqual(lp._content_text("abc"), "abc")

    def test_none_and_junk(self):
        self.assertEqual(lp._content_text(None), "")
        self.assertEqual(lp._content_text(42), "")

    def test_blocks_keep_text_drop_thinking(self):
        blocks = [{"type": "thinking", "thinking": [{"type": "text", "text": "secret"}]},
                  {"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}]
        self.assertEqual(lp._content_text(blocks), "Hello world")

    def test_single_block_dict(self):
        self.assertEqual(lp._content_text({"type": "text", "text": "x"}), "x")


class OpenAIStreamTest(unittest.TestCase):
    CONN = {"id": "c", "type": "openai", "base_url": "https://api.example/v1", "api_key": "k"}

    def test_mistral_block_stream_yields_only_text(self):
        with _FixtureTransport("mistral_large4_stream.sse"):
            toks = _run(_collect(lp.OpenAIAdapter(), self.CONN, "mistral-large-4"))
        self.assertTrue(all(isinstance(t, str) for t in toks))
        self.assertEqual("".join(toks), "Hello, how can I help?")
        self.assertNotIn("user greets", "".join(toks))

    def test_recorded_mistral_large4(self):
        # Recorded from the Mistral API on 2026-10-30 (reasoning on by default).
        with _FixtureTransport("mistral_large4_recorded.sse"):
            toks = _run(_collect(lp.OpenAIAdapter(), self.CONN, "mistral-large-4"))
        self.assertTrue(all(isinstance(t, str) for t in toks))
        self.assertEqual("".join(toks).strip().lower().strip("."), "hello")

    def test_recorded_openrouter_qwen_reasoning_stream(self):
        # Recorded from OpenRouter (Alibaba) on 2026-10-30: reasoning arrives in a
        # separate `reasoning` field and must not reach the user.
        with _FixtureTransport("openrouter_qwen38flash_recorded.sse"):
            toks = _run(_collect(lp.OpenAIAdapter(), self.CONN, "qwen/qwen3.8-flash"))
        self.assertEqual("".join(toks).strip().lower().strip("."), "hello")

    def test_openrouter_reasoning_field_ignored_and_usage_chunk_tolerated(self):
        with _FixtureTransport("openrouter_qwen_stream.sse"):
            toks = _run(_collect(lp.OpenAIAdapter(), self.CONN, "qwen/qwen3.8-flash"))
        self.assertEqual("".join(toks), "Yes.")



from src.services import llm_capabilities as caps  # noqa: E402

MISTRAL = {"id": "mistral", "type": "openai", "base_url": "https://api.mistral.ai/v1", "api_key": "k"}
OPENROUTER = {"id": "or", "type": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key": "k"}
LMSTUDIO = {"id": "lms", "type": "openai", "base_url": "http://host.docker.internal:1234/v1"}
ANTHROPIC = {"id": "an", "type": "anthropic", "base_url": "https://api.anthropic.com", "api_key": "k"}


class CapabilitiesTest(unittest.TestCase):
    """Rules verified live on 2026-10-30 (Mistral API, OpenRouter)."""

    def test_provider_inference(self):
        self.assertEqual(caps.provider_kind(MISTRAL), "mistral")
        self.assertEqual(caps.provider_kind(OPENROUTER), "openrouter")
        self.assertEqual(caps.provider_kind(LMSTUDIO), "openai_compatible")
        self.assertEqual(caps.provider_kind({**LMSTUDIO, "provider": "openrouter"}), "openrouter")
        self.assertEqual(caps.provider_kind(ANTHROPIC), "anthropic")

    def test_mistral_large4_cannot_switch_off(self):
        fields, note = caps.reasoning_mapping("mistral", "mistral-large-4", "off")
        self.assertEqual(fields, {})
        self.assertIn("cannot", note)
        self.assertEqual(caps.reasoning_mapping("mistral", "mistral-large-4", "low")[0], {"reasoning_effort": "low"})

    def test_mistral_small_only_none_or_high(self):
        self.assertEqual(caps.reasoning_mapping("mistral", "mistral-small-latest", "off")[0], {"reasoning_effort": "none"})
        fields, note = caps.reasoning_mapping("mistral", "mistral-medium-latest", "low")
        self.assertEqual(fields, {"reasoning_effort": "high"})
        self.assertTrue(note)

    def test_openrouter_reasoning(self):
        self.assertEqual(caps.reasoning_mapping("openrouter", "qwen/qwen3.8-flash", "off")[0], {"reasoning": {"enabled": False}})
        self.assertEqual(caps.reasoning_mapping("openrouter", "x", "high")[0], {"reasoning": {"effort": "high"}})

    def test_default_sends_nothing(self):
        for kind in caps.PROVIDER_KINDS:
            self.assertEqual(caps.reasoning_mapping(kind, "m", None), ({}, ""))

    def test_body_extras_per_provider(self):
        b = caps.openai_body_extras(MISTRAL, "mistral-large-4", 0.3, 500, None, "ck")
        self.assertEqual(b, {"temperature": 0.3, "max_tokens": 500})  # no stream_options, no cache key (opt-in)
        b = caps.openai_body_extras({**MISTRAL, "prompt_cache_key": True}, "mistral-large-4", None, None, None, "ck")
        self.assertEqual(b, {"prompt_cache_key": "ck"})
        b = caps.openai_body_extras(LMSTUDIO, "qwen3", None, None, "off", None)
        self.assertEqual(b, {"chat_template_kwargs": {"enable_thinking": False}, "stream_options": {"include_usage": True}})
        # Gemma has no thinking switch: Qwen's kwarg can break its chat template (oMLX/LM Studio)
        b = caps.openai_body_extras(LMSTUDIO, "gemma-3-27b-it", None, None, "off", None)
        self.assertNotIn("chat_template_kwargs", b)
        b = caps.openai_body_extras({**OPENROUTER, "routing": {"order": ["alibaba"], "allow_fallbacks": False}},
                                    "qwen/qwen3-235b", None, None, None, None)
        self.assertEqual(b["provider"], {"order": ["alibaba"], "allow_fallbacks": False})
        self.assertNotIn("num_ctx", caps.openai_body_extras(MISTRAL, "m", None, None, None, None))

    def test_describe_flags_ignored_controls(self):
        d = caps.describe(MISTRAL, "mistral-large-4", {"temperature": 0.2, "num_ctx": 100000, "reasoning": "off"})
        self.assertEqual(d["controls"]["temperature"]["status"], "sent")
        self.assertEqual(d["controls"]["num_ctx"]["status"], "ignored")
        self.assertEqual(d["controls"]["reasoning"]["status"], "ignored")
        self.assertNotIn("off", d["controls"]["reasoning"]["options"])

    def test_openrouter_supported_parameters_flag_noops(self):
        # mistral-large-2512 on OpenRouter does not list "reasoning" (checked 2026-10-30)
        supported = ['frequency_penalty', 'max_tokens', 'temperature', 'top_p']
        d = caps.describe(OPENROUTER, "mistralai/mistral-large-2512", {"reasoning": "off", "temperature": 0.2}, supported)
        self.assertEqual(d["controls"]["reasoning"]["status"], "ignored")
        self.assertEqual(d["controls"]["reasoning"]["options"], [])
        self.assertEqual(d["controls"]["temperature"]["status"], "sent")

    def test_rejected_optional_fields(self):
        err = '{"message":"reasoning_effort=\'low\' is not supported for this model"}'
        self.assertEqual(caps.rejected_optional_fields(err, {"reasoning_effort": "low", "temperature": 1}), ["reasoning_effort"])
        # A server that rejects without naming the field: drop every optional field we added
        body = {"stream_options": {"include_usage": True}, "chat_template_kwargs": {}, "temperature": 0.1}
        self.assertEqual(sorted(caps.rejected_optional_fields('{"error":"bad request"}', body)),
                         ["chat_template_kwargs", "stream_options"])


class _SequenceTransport:
    """Returns the given (status, fixture/body) responses in order; records request JSON."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []

    def __enter__(self):
        import json as _json
        self._orig = lp.httpx.AsyncClient
        real = self._orig

        def handler(request):
            self.bodies.append(_json.loads(request.content))
            status, payload = self.responses.pop(0)
            content = (FIXTURES / payload).read_bytes() if payload.endswith(".sse") else payload.encode()
            return httpx.Response(status, content=content)

        lp.httpx.AsyncClient = lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler),
                                                       **{k: v for k, v in kw.items() if k != "transport"})
        return self

    def __exit__(self, *a):
        lp.httpx.AsyncClient = self._orig


class AdapterBehaviourTest(unittest.TestCase):
    def _stream(self, adapter, conn, model, reasoning=None, usage=None, messages=None):
        async def go():
            out = []
            async for t in adapter.stream(conn, model, messages or [{"role": "user", "content": "hi"}],
                                          None, None, None, reasoning=reasoning, usage=usage):
                out.append(t)
            return "".join(out)
        return _run(go())

    def test_rejected_field_is_dropped_and_retried_once(self):
        err = '{"message":"reasoning_effort low is not supported for this model"}'
        with _SequenceTransport([(400, err), (200, "mistral_large4_recorded.sse")]) as t:
            text = self._stream(lp.OpenAIAdapter(), MISTRAL, "mistral-medium-latest", reasoning="low")
        self.assertEqual(text.strip().lower().strip("."), "hello")
        self.assertIn("reasoning_effort", t.bodies[0])
        self.assertNotIn("reasoning_effort", t.bodies[1])

    def test_other_errors_still_raise(self):
        with _SequenceTransport([(400, '{"message":"bad model"}')]):
            with self.assertRaises(httpx.HTTPStatusError):
                self._stream(lp.OpenAIAdapter(), MISTRAL, "nope")

    def test_usage_from_recorded_streams(self):
        for fixture in ("mistral_large4_recorded.sse", "openrouter_qwen38flash_recorded.sse"):
            usage: dict = {}
            with _SequenceTransport([(200, fixture)]):
                self._stream(lp.OpenAIAdapter(), OPENROUTER, "m", usage=usage)
            self.assertGreater(usage.get("prompt_tokens", 0), 0, fixture)
            self.assertIn("cached_tokens", usage)

    def test_anthropic_cache_breakpoints_and_usage(self):
        usage: dict = {}
        msgs = [{"role": "system", "content": "S" * 50}, {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
        with _SequenceTransport([(200, "anthropic_stream.sse")]) as t:
            text = self._stream(lp.AnthropicAdapter(), ANTHROPIC, "claude-x", usage=usage, messages=msgs)
        body = t.bodies[0]
        self.assertEqual(text, "Hello")
        self.assertEqual(body["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["messages"][-2]["content"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", body["messages"][-1]["content"][-1])
        self.assertEqual(usage, {"prompt_tokens": 5040, "cached_tokens": 5000, "completion_tokens": 12})

    def test_anthropic_thinking_drops_temperature(self):
        with _SequenceTransport([(200, "anthropic_stream.sse")]) as t:
            async def go():
                async for _ in lp.AnthropicAdapter().stream(ANTHROPIC, "claude-x", [{"role": "user", "content": "x"}],
                                                            0.5, 1000, None, reasoning="medium"):
                    pass
            _run(go())
        body = t.bodies[0]
        self.assertNotIn("temperature", body)
        self.assertEqual(body["thinking"]["budget_tokens"], 8192)
        self.assertGreater(body["max_tokens"], 8192)

    def test_cache_key_is_a_hash_of_the_running_job(self):
        from src.services import llm_usage
        self.assertIsNone(llm_usage.cache_key())
        tok = llm_usage.current_job.set("JOB123")
        try:
            key = llm_usage.cache_key()
            self.assertNotIn("JOB123", key)
            self.assertEqual(len(key), 32)
        finally:
            llm_usage.current_job.reset(tok)


class TranslationEngineTest(unittest.TestCase):
    """The translation engine through the real fallback path (document_translator → llm)."""

    @classmethod
    def setUpClass(cls):
        from src.services.connection_registry import connections
        if not connections.get("mistral"):
            connections.add({**MISTRAL, "id": "mistral"})

    def test_reasoning_defaults_off_and_default_sends_nothing(self):
        from src.services import document_translator as dt
        self.assertEqual(dt._engine_config({}, "mistral", "m")["reasoning"], "off")
        self.assertIsNone(dt._engine_config({"translation_reasoning": "default"}, "mistral", "m")["reasoning"])
        self.assertEqual(dt._engine_config({"translation_reasoning": "high"}, "mistral", "m")["reasoning"], "high")

    def test_mistral_blocks_never_reach_the_document_and_usage_is_recorded(self):
        from src.services import document_translator as dt, llm_usage
        chain = [dt._engine_config({}, "mistral", "mistral-large-4")]
        tok = llm_usage.current_job.set("JOBX")
        try:
            with _SequenceTransport([(200, "mistral_large4_recorded.sse")]) as t:
                out = _run(lp.llm.chat_with_fallback([{"role": "user", "content": "hi"}], chain))
        finally:
            llm_usage.current_job.reset(tok)
        self.assertEqual(out.strip().lower().strip("."), "hello")
        self.assertNotIn("reasoning_effort", t.bodies[0])  # large-4 cannot switch off: nothing sent, no 400
        job = llm_usage.job_summary("JOBX")["engine"]
        self.assertEqual(job["calls"], 1)
        self.assertGreater(job["prompt_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
