"""LLM client — Claude API via urllib (zero deps).

Handles timeouts, retries with exponential backoff + jitter,
and structured logging of every request.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
import urllib.error
import urllib.request
from typing import Optional

from lab.config import (
    DOTENV_PATH,
    LLM_BACKOFF_BASE_S,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_S,
    SOULS_DIR,
)

logger = logging.getLogger('lab.llm')

# ── API key loading ──────────────────────────────────────

_api_key: Optional[str] = None


def _load_api_key() -> str:
    """Load ANTHROPIC_API_KEY from env or .env file."""
    global _api_key
    if _api_key:
        return _api_key

    # 1. Environment variable
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if key:
        _api_key = key
        return key

    # 2. .env file (trading_bot/.env)
    if DOTENV_PATH.exists():
        with open(DOTENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith('ANTHROPIC_API_KEY='):
                    key = line.split('=', 1)[1].strip().strip('"').strip("'")
                    if key:
                        _api_key = key
                        os.environ['ANTHROPIC_API_KEY'] = key
                        return key

    raise RuntimeError(
        "ANTHROPIC_API_KEY not found. Set it in environment or "
        f"add to {DOTENV_PATH}"
    )


# ── Soul loading ────────────────────────────────────────

def load_soul(agent_name: str) -> str:
    """Load system prompt from lab/souls/{agent_name}.md."""
    soul_path = SOULS_DIR / f'{agent_name}.md'
    if not soul_path.exists():
        logger.warning(f"No soul file for {agent_name} at {soul_path}")
        return ''
    return soul_path.read_text().strip()


# ── Hashing ─────────────────────────────────────────────

def _hash(text: str) -> str:
    """Short SHA-256 hash of text for logging."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# ── Core API call ────────────────────────────────────────

def call(
    prompt: str,
    system: str = '',
    model: str = LLM_MODEL,
    max_tokens: int = LLM_MAX_OUTPUT_TOKENS,
    timeout: float = LLM_TIMEOUT_S,
    max_retries: int = LLM_MAX_RETRIES,
    temperature: float = 0.3,
) -> dict:
    """Call Claude API with retries and structured logging.

    Args:
        prompt: User message content.
        system: System prompt (loaded from soul file typically).
        model: Model identifier.
        max_tokens: Max output tokens.
        timeout: Request timeout in seconds.
        max_retries: Max retry attempts.
        temperature: Sampling temperature (low for deterministic output).

    Returns:
        dict with keys:
            - text: Response text content
            - model: Model used
            - input_tokens: Input token count
            - output_tokens: Output token count
            - latency_ms: Request latency in milliseconds
            - request_id: API request ID
            - prompt_hash: Hash of prompt for dedup
            - response_hash: Hash of response for provenance
            - stop_reason: Why generation stopped

    Raises:
        RuntimeError: After all retries exhausted.
        ValueError: If API key is missing.
    """
    api_key = _load_api_key()

    payload = {
        'model': model,
        'max_tokens': max_tokens,
        'temperature': temperature,
        'messages': [{'role': 'user', 'content': prompt}],
    }
    if system:
        payload['system'] = system

    body = json.dumps(payload).encode('utf-8')
    prompt_hash = _hash(prompt)

    last_error = None
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=body,
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                },
                method='POST',
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                latency_ms = round((time.monotonic() - t0) * 1000)
                data = json.loads(resp.read().decode('utf-8'))

            # Extract response
            text = ''
            for block in data.get('content', []):
                if block.get('type') == 'text':
                    text += block.get('text', '')

            usage = data.get('usage', {})
            result = {
                'text': text,
                'model': data.get('model', model),
                'input_tokens': usage.get('input_tokens', 0),
                'output_tokens': usage.get('output_tokens', 0),
                'latency_ms': latency_ms,
                'request_id': data.get('id', ''),
                'prompt_hash': prompt_hash,
                'response_hash': _hash(text),
                'stop_reason': data.get('stop_reason', ''),
            }

            logger.info(
                f"LLM call OK: model={result['model']} "
                f"in={result['input_tokens']} out={result['output_tokens']} "
                f"latency={latency_ms}ms prompt={prompt_hash} "
                f"resp={result['response_hash']} attempt={attempt + 1}"
            )
            return result

        except urllib.error.HTTPError as e:
            latency_ms = round((time.monotonic() - t0) * 1000)
            last_error = e
            error_body = ''
            try:
                error_body = e.read().decode('utf-8')[:500]
            except Exception:
                pass

            # Don't retry on 4xx (except 429 rate limit and 529 overloaded)
            if e.code in (429, 529) or e.code >= 500:
                wait = _backoff(attempt)
                logger.warning(
                    f"LLM call {e.code} (attempt {attempt + 1}/{max_retries + 1}): "
                    f"{error_body[:200]}. Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
                continue
            else:
                logger.error(
                    f"LLM call failed {e.code} (no retry): "
                    f"{error_body[:200]} latency={latency_ms}ms"
                )
                raise RuntimeError(
                    f"Claude API error {e.code}: {error_body[:200]}"
                ) from e

        except (urllib.error.URLError, TimeoutError, OSError) as e:
            latency_ms = round((time.monotonic() - t0) * 1000)
            last_error = e
            wait = _backoff(attempt)
            logger.warning(
                f"LLM call network error (attempt {attempt + 1}/{max_retries + 1}): "
                f"{str(e)[:200]}. Retrying in {wait:.1f}s..."
            )
            time.sleep(wait)
            continue

    raise RuntimeError(
        f"Claude API failed after {max_retries + 1} attempts: {last_error}"
    )


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^attempt + random jitter."""
    base = LLM_BACKOFF_BASE_S * (2 ** attempt)
    jitter = random.uniform(0, base * 0.5)
    return min(base + jitter, 60.0)  # cap at 60s


# ── Convenience functions ────────────────────────────────

def ask(prompt: str, agent_name: str = '', **kwargs) -> str:
    """Simple call: load soul, return text only."""
    system = load_soul(agent_name) if agent_name else ''
    result = call(prompt, system=system, **kwargs)
    return result['text']


def ask_json(prompt: str, agent_name: str = '', **kwargs) -> dict:
    """Call and parse response as JSON. Strips markdown fences.

    Raises ValueError with context on JSON parse failure so callers
    can fall back gracefully (e.g. boss → template tasks).
    """
    text = ask(prompt, agent_name=agent_name, **kwargs)
    # Strip ```json ... ``` fences
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        # Remove first line (```json) and last line (```)
        if lines[-1].strip() == '```':
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = '\n'.join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Include first 200 chars of raw text for debugging
        preview = text[:200].replace('\n', '\\n')
        raise ValueError(
            f"LLM returned invalid JSON: {e}. Preview: {preview}"
        ) from e
