from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from llm import LLM_MODEL, LLMError, generate

app = FastAPI(title="python-models", version="0.1.0")


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)

class GenerateResponse(BaseModel):
    model: str
    output: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": LLM_MODEL}


@app.post("/generate", response_model=GenerateResponse)
async def generate_endpoint(request: GenerateRequest) -> GenerateResponse:
    try:
        output = await generate(
            prompt=request.prompt,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    return GenerateResponse(model=LLM_MODEL, output=output)
