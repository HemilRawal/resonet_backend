"""
LLM client for DACRO — Groq primary, Gemini secondary, Claude tertiary, templated fallback.
Exposes a single async function: generate_explanation(decision_context: dict) -> str.

Provider priority:
  1. Groq  (llama-3.3-70b-versatile) — high RPM, large context window, no input-size limits
  2. Gemini (gemini-2.0-flash)        — secondary fallback
  3. Claude (claude-sonnet-4-*)       — tertiary fallback (only if USE_CLAUDE=true or both above fail)
  4. Templated string                 — demo-safe last resort
"""

import json
import logging
from typing import Optional

import config

logger = logging.getLogger(__name__)

_PROMPT_PREFIX = (
    "You are an emergency crisis AI explaining a resource allocation decision "
    "to a human coordinator. Be concise, factual, urgent in tone. 3 sentences max.\n\n"
    "Decision context:\n{context}\n\n"
    "Write: RATIONALE: [why this decision was made] | "
    "COUNTERFACTUAL: [what would have happened without this allocation]"
)


def _build_prompt(decision_context: dict) -> str:
    return _PROMPT_PREFIX.format(context=json.dumps(decision_context, indent=2))


def _build_fallback(decision_context: dict) -> str:
    """Construct a templated explanation without any LLM call."""
    resource_type = decision_context.get("resource_type", "resources")
    requester = decision_context.get("requester_agent", "requester")
    winner = decision_context.get("winner_agent", "provider")
    urgency = decision_context.get("urgency_score", "high")
    zone_id = decision_context.get("zone_id", "affected zone")
    return (
        f"RATIONALE: {resource_type} allocated to {requester} from {winner} "
        f"due to {urgency} urgency in zone {zone_id}. | "
        f"COUNTERFACTUAL: Without this allocation, {requester} would have "
        f"entered resource-critical state."
    )


async def _try_groq(prompt: str) -> Optional[str]:
    """Primary provider — Groq API via openai-compatible SDK (groq package)."""
    try:
        from groq import AsyncGroq  # type: ignore
        client = AsyncGroq(api_key=config.GROQ_API_KEY)
        chat_completion = await client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.3,
        )
        text = chat_completion.choices[0].message.content.strip()
        logger.info("LLM: Groq response received (%d chars)", len(text))
        return text
    except Exception as exc:
        logger.warning("LLM: Groq failed — %s", exc)
        return None


async def _try_gemini(prompt: str) -> Optional[str]:
    """Secondary provider — Gemini API."""
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        text = response.text.strip()
        logger.info("LLM: Gemini response received (%d chars)", len(text))
        return text
    except Exception as exc:
        logger.warning("LLM: Gemini failed — %s", exc)
        return None


async def _try_claude(prompt: str) -> Optional[str]:
    """Tertiary provider — Anthropic Claude."""
    try:
        import anthropic  # type: ignore
        client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        logger.info("LLM: Claude response received (%d chars)", len(text))
        return text
    except Exception as exc:
        logger.warning("LLM: Claude failed — %s", exc)
        return None


async def generate_explanation(decision_context: dict) -> str:
    """
    Generate a RATIONALE | COUNTERFACTUAL explanation for a negotiation decision.
    Provider priority: Groq → Gemini → Claude → templated fallback.
    """
    prompt = _build_prompt(decision_context)

    # 1. Try Groq first (primary — no input-size quota issues)
    result = await _try_groq(prompt)
    if result:
        return result
    logger.info("LLM: Groq failed, falling back to Gemini")

    # 2. Try Gemini (secondary)
    if not config.USE_CLAUDE:
        result = await _try_gemini(prompt)
        if result:
            return result
        logger.info("LLM: Gemini failed, falling back to Claude")

    # 3. Try Claude (tertiary)
    result = await _try_claude(prompt)
    if result:
        return result

    logger.warning("LLM: all providers failed — using templated fallback")
    return _build_fallback(decision_context)
