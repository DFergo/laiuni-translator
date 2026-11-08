# Model recommendations

**As of 2026-11-08.** Models change fast: check that a model is still offered (and its price) on the provider's site, and tell the user how old this list is.

## What this project has actually run for translation
- **Mistral API** with `mistral-large-4` — works. It cannot switch reasoning off; the app knows (the admin shows what applies to each connection and model) and drops the field the provider rejects. Clean output, token usage recorded.
- **OpenRouter** with a Qwen model — works with reasoning off. Provider routing options exist on the connection.
- **Local default of the project's author**: `Qwen3-235B` served by oMLX on a Mac Studio (an `openai`-type connection).
- Not tested here for translation, but widely used: OpenAI and Anthropic models through their connection types.

## Recommendations carried over from the sister app (HRDD Helper team, 2026-10-31)
These came from testing **chat** quality, not translation; treat them as starting points and compare on a real document.
| Use | Recommendation | Why |
|---|---|---|
| Best balance (quality, cost, speed) | **DeepSeek V4.1** | The most balanced model in those tests. Via its own API (data processed in China) or through OpenRouter, where you can choose the serving provider and restrict to no-retention providers. |
| Privacy first, cloud | **Mistral** models | EU provider. The connection has an option to send a per-job prompt-cache key (cheaper repeated prefixes). |
| Local, 32–48 GB of memory | **Qwen3.6 27B** or **Gemma 4 31B** | Run with LM Studio or Ollama, 4-bit quantization. |

## Notes
- Translation quality differs by language pair and model. Test the languages the organisation actually needs with a real paragraph before committing.
- Keep the temperature low (default 0.1) and reasoning off unless the model requires otherwise.
- Long documents are cut at headings into chunks, each translated with the glossary terms that appear in it; a larger context window is not needed for that.
- With many documents at once, check the provider's rate limits before raising `max_concurrent` (guide `inference`).
