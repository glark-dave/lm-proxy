import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import copy
import httpx
import json
import os
from typing import Dict, Any, List
from contextlib import asynccontextmanager

# --- Configuration ---
LITELLM_PROXY_URL: str = os.getenv("LITELLM_PROXY_URL", "http://localhost:8000")
FASTAPI_PROXY_PORT: int = int(os.getenv("FASTAPI_PROXY_PORT", "8001"))
DEFAULT_LITELLM_MODEL_ALIAS: str = os.getenv("DEFAULT_LITELLM_MODEL_ALIAS", "groq-llama4-scout")

httpx_client = httpx.AsyncClient(timeout=30.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("INFO: FastAPI proxy starting up...")
    yield
    print("INFO: FastAPI proxy shutting down...")
    await httpx_client.aclose()
    print("INFO: HTTPX client closed.")


app = FastAPI(
    title="LM-Studio Compatibility Proxy",
    description="Proxies LM-Studio requests to LiteLLM.",
    version="0.0.1",
    lifespan=lifespan
)


# --- Helper Functions for Model Discovery ---

async def _fetch_models_from_litellm() -> List[Dict[str, Any]]:
    """
    Fetches the list of models from the LiteLLM.
    """
    print(f"INFO: Attempting to fetch models from LiteLLM at {LITELLM_PROXY_URL}/v1/models")
    try:
        litellm_response = await httpx_client.get(f"{LITELLM_PROXY_URL}/v1/models", timeout=5.0)
        litellm_response.raise_for_status()
        litellm_data = litellm_response.json()
        models = litellm_data.get("data", [])

        if not models:
            raise ValueError("LiteLLM returned no models.")

        print(f"INFO: Successfully fetched {len(models)} models from LiteLLM.")
        return models

    except Exception as e:
        status_code = 502 if isinstance(e, (httpx.RequestError, json.JSONDecodeError)) else 500
        detail_message = f"An error occurred while fetching models from LiteLLM: {e}"
        print(f"ERROR: {detail_message}")
        raise HTTPException(status_code=status_code, detail=detail_message)


def _transform_litellm_model_to_lmstudio_format(model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms a single model dictionary fetched from LiteLLM into LM-Studio format.
    """
    model_id: str = model.get("id", DEFAULT_LITELLM_MODEL_ALIAS)
    return {
        "id": model_id,
        "object": "model",
        "type": "chat",
        "publisher": model.get("owned_by", "litellm-proxied"),
        "arch": "unknown",
        "compatibility_type": "openai",
        "quantization": "unknown",
        "state": "loaded",
        "max_context_length": 32768
    }


def tidy_message(original):
    """Strip tool_calls from a message."""
    message = copy.deepcopy(original)
    # Exclude if message.get("tool_calls") is en empty list.
    if "tool_calls" in message and (message["role"] != "assistant" or message.get("tool_calls") == []):
        del message['tool_calls']

    # Some LLMs don't like "user" messages which claim to be system messages.
    if message["role"] == "user" and "This is a system message." in message.get("content", ""):
        message["role"] = "system"

    return message

def _prepare_openai_chat_request_body(lmstudio_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms an incoming LM-Studio chat completion request into a LiteLLM request.
    """
    max_tokens = lmstudio_request["max_tokens"]
    tools = lmstudio_request.get("tools", [])
    processed_messages = [tidy_message(message) for message in lmstudio_request.get("messages", [])]
    all_system_messages = all(message.get("role") == "system" for message in processed_messages)
    if all_system_messages and processed_messages:  # Ensure there's at least one message processed
        print("INFO: All messages are system messages. Adding dummy user message for Anthropic compatibility.")
        processed_messages.append({"role": "user", "content": "Please continue."})

    return {
      "model": lmstudio_request["model"],
      "stream": lmstudio_request.get("stream", False),
       **({"tools": tools} if tools else {}),
      "messages": processed_messages,
      **({"max_tokens": max_tokens} if "max_tokens" in lmstudio_request and max_tokens != -1 else {})
    }


async def _stream_litellm_response_to_client(
        litellm_response_stream: httpx.Response,
):
    """
    Asynchronous generator that processes and forwards the SSE stream from LiteLLM.
    """
    try:
        async with litellm_response_stream as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    yield f"{line}\n"
                    continue
                yield await _process_and_modify_json_line(line)
        print("INFO: Stream generator finished gracefully.")
    except Exception as e:
        status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else 500
        detail_message = f"An unexpected error occurred during streaming: {e}"
        print(f"ERROR: {detail_message}")
        raise HTTPException(status_code=status_code, detail=detail_message)


async def _process_and_modify_json_line(line: str) -> str:
    json_payload = line[len("data:"):].strip()
    if json_payload == "[DONE]":
        print("INFO: Detected [DONE] signal. Yielding and terminating stream.")
        return "data: [DONE]\n\n"
    try:
        data_obj = json.loads(json_payload)
        data_obj["system_fingerprint"] = "proxy_fingerprint"
        modified_line = f"data: {json.dumps(data_obj)}\n\n"
        return modified_line
    except json.JSONDecodeError:
        print(f"WARNING: Could not parse JSON from line, passing through: {line}")
        return f"{line}\n\n"


# --- API Endpoints ---
@app.get("/api/v0/models")
async def get_lmstudio_models_v0() -> JSONResponse:
    """
    Fetches models from LiteLLM and transforms them into LM Studio format.
    """
    print("INFO: Received GET /api/v0/models request (LM Studio format).")
    litellm_models = await _fetch_models_from_litellm()
    transformed_models = [_transform_litellm_model_to_lmstudio_format(model) for model in litellm_models]
    return JSONResponse(content={"object": "list", "data": transformed_models})


@app.post("/api/v0/chat/completions")
async def proxy_lmstudio_chat_completions(request: Request) -> StreamingResponse:
    """
    Handles LM Studio specific chat completion requests, proxying through LiteLLM
    """
    print("INFO: Received POST /api/v0/chat/completions request (LM Studio format).")
    try:
        openai_compatible_request_body = _prepare_openai_chat_request_body(await request.json())

        litellm_response_stream = httpx_client.stream(
            "POST",
            f"{LITELLM_PROXY_URL}/v1/chat/completions",
            json=openai_compatible_request_body,
        )
        return StreamingResponse(_stream_litellm_response_to_client(litellm_response_stream),
                                 media_type="text/event-stream")

    except Exception as e:
        status_code = 400 if isinstance(e, json.JSONDecodeError) else 500
        detail_message = f"An error occurred during request processing: {e}"
        print(f"ERROR: {detail_message}")
        raise HTTPException(status_code=status_code, detail=detail_message)


# --- How to run this FastAPI app ---
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=FASTAPI_PROXY_PORT,
        reload=False
    )