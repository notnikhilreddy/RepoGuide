"""M5 provider adapter. Reuses user's existing multi-provider llm.py.

Generation is provider-agnostic. Streaming uses native APIs when supported and
falls back to a single non-streaming response on unsupported server features.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from repoguide.config import settings


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    model: str


def identity() -> ProviderIdentity:
    p = settings.llm_provider
    if p == "gemini":
        return ProviderIdentity(p, settings.gemini_model)
    if p == "opencode":
        return ProviderIdentity(p, settings.opencode_model)
    if p == "ollama":
        return ProviderIdentity(p, getattr(settings, "ollama_model", "qwen3.5:4b"))
    raise ValueError(f"Unsupported LLM provider: {p}")


def complete(prompt: str) -> str:
    # No replacement of working llm.py and its client settings.
    from repoguide.llm import generate_answer
    return generate_answer(prompt)


def stream(prompt: str) -> Iterator[str]:
    """Native streaming tokens/deltas. Tokens are unverified until final validation.

    Streaming may be unavailable on OpenAI-compatible gateways. In that case
    fall back once to a normal completion, but never retry after deltas were sent.
    """
    from repoguide import llm
    provider = identity().provider
    delivered = False
    try:
        if provider == "gemini":
            from google.genai import types
            chunks = llm.get_gemini_client().models.generate_content_stream(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=llm.SYSTEM_PROMPT,
                    temperature=0.1, max_output_tokens=3500,
                ),
            )
            for chunk in chunks:
                delta = getattr(chunk, "text", None)
                if delta:
                    delivered = True
                    yield delta
        elif provider == "opencode":
            events = llm.get_opencode_client().responses.create(
                model=settings.opencode_model,
                instructions=llm.SYSTEM_PROMPT,
                input=prompt,
                max_output_tokens=3500,
                stream=True,
            )
            for event in events:
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        delivered = True
                        yield delta
        elif provider == "ollama":
            # Ollama OpenAI-compatible chat streaming is more widely supported
            # than the Responses streaming surface across Ollama releases.
            events = llm.get_ollama_client().chat.completions.create(
                model=identity().model,
                messages=[
                    {"role": "system", "content": llm.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=3500,
                stream=True,
            )
            for event in events:
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    delivered = True
                    yield delta
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    except Exception:
        if delivered:
            raise  # never silently append a second answer after partial output
        yield complete(prompt)
