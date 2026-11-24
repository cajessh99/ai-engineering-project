import os
from functools import cache

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()  # reads ANTHROPIC_API_KEY from .env

MODEL = "claude-opus-5-5"

app = FastAPI()


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    answer: str


@cache
def get_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic()


@app.get("/")
def hello():
    return {"message": "Hello, world!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest):
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        raise HTTPException(500, "ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example).")

    try:
        response = await get_client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            # If the model declines on safety grounds, the API retries on a
            # fallback model within the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": body.question}],
        )
    except anthropic.AuthenticationError:
        raise HTTPException(500, "Invalid Anthropic API key. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Rate limited by the Anthropic API. Try again shortly.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Could not reach the Anthropic API.")

    if response.stop_reason == "refusal":
        raise HTTPException(422, "The model declined to answer this question.")

    answer = "".join(b.text for b in response.content if b.type == "text")
    return AskResponse(answer=answer)
