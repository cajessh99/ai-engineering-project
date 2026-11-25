import logging
import os
from functools import cache
from typing import Annotated

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, StringConstraints

load_dotenv()  # reads ANTHROPIC_API_KEY from .env

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
EFFORT = "medium"
MAX_QUESTION_CHARS = 4000
REQUEST_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 2

# Stop reasons that mean the answer was cut off before Claude finished it.
TRUNCATED_STOP_REASONS = {"max_tokens", "model_context_window_exceeded"}

logger = logging.getLogger(__name__)

app = FastAPI()


class AskRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS),
    ]


class AskResponse(BaseModel):
    answer: str


@cache
def get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES)


def extract_answer(content) -> str:
    """Join the text blocks of the final model's answer.

    With server-side fallback, a declining model's partial output can come
    before a "fallback" block, so only text after the last one is kept.
    """
    last_fallback = max(
        (i for i, block in enumerate(content) if block.type == "fallback"), default=-1
    )
    return "".join(block.text for block in content[last_fallback + 1 :] if block.type == "text")


@app.get("/")
def hello():
    """Return a hello-world greeting."""
    return {"message": "Hello, world!"}


@app.get("/health")
def health():
    """Report that the server is running."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest):
    """Answer a question with Claude."""
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        raise HTTPException(
            500,
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) "
            "in .env (see .env.example).",
        )

    try:
        response = await get_client().beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": EFFORT},
            # If the model declines on safety grounds, the API retries on a
            # fallback model within the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": body.question}],
        )
    except anthropic.AuthenticationError as e:
        logger.error("Anthropic authentication failed: %s", e)
        raise HTTPException(500, "Invalid Anthropic API key. Check ANTHROPIC_API_KEY in .env.") from e
    except anthropic.RateLimitError as e:
        logger.warning("Rate limited by the Anthropic API: %s", e)
        raise HTTPException(429, "Rate limited by the Anthropic API. Try again shortly.") from e
    except anthropic.APIStatusError as e:
        # Questions are validated above, so a remaining API error is upstream
        # or a server misconfiguration. Log the details; don't send them out.
        logger.error("Anthropic API error %s: %s", e.status_code, e)
        raise HTTPException(502, f"The Anthropic API returned an error ({e.status_code}).") from e
    except anthropic.APIConnectionError as e:
        logger.error("Could not reach the Anthropic API: %s", e)
        raise HTTPException(502, "Could not reach the Anthropic API.") from e

    if response.stop_reason == "refusal":
        raise HTTPException(422, "The model declined to answer this question.")
    if response.stop_reason in TRUNCATED_STOP_REASONS:
        raise HTTPException(502, "The answer was cut off before it finished.")

    answer = extract_answer(response.content)
    if not answer:
        raise HTTPException(502, "Claude returned no text.")
    return AskResponse(answer=answer)
