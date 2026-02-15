from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
import time
import logging

app = FastAPI()

# ---- CONFIGURATION ----
MAX_TOKENS = 9  # Burst capacity
REFILL_RATE = 41 / 60  # tokens per second


# ---- IN-MEMORY STORE ----
rate_limit_store = {}


# ---- LOGGING SETUP ----
logging.basicConfig(level=logging.INFO)


# ---- REQUEST SCHEMA ----
class RequestBody(BaseModel):
    userId: str
    input: str
    category: str


# ---- VALIDATION ERROR HANDLER ----
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "blocked": True,
            "reason": "Invalid request format",
            "confidence": 0.99
        }
    )


# ---- GENERIC ERROR HANDLER ----
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "blocked": True,
            "reason": "Internal server error",
            "confidence": 0.50
        }
    )


# ---- TOKEN BUCKET CHECK ----
def check_rate_limit(user_key: str):
    current_time = time.time()

    if user_key not in rate_limit_store:
        rate_limit_store[user_key] = {
            "tokens": MAX_TOKENS,
            "last_refill": current_time
        }

    bucket = rate_limit_store[user_key]

    # Refill tokens
    elapsed = current_time - bucket["last_refill"]
    refill = elapsed * REFILL_RATE
    bucket["tokens"] = min(MAX_TOKENS, bucket["tokens"] + refill)
    bucket["last_refill"] = current_time

    if bucket["tokens"] >= 1:
        bucket["tokens"] -= 1
        return True, 0
    else:
        # Calculate retry time
        retry_after = (1 - bucket["tokens"]) / REFILL_RATE
        return False, round(retry_after)


# ---- MAIN ENDPOINT ----
@app.post("/validate")
async def validate(data: RequestBody, request: Request):

    if data.category != "Rate Limiting":
        raise HTTPException(status_code=400, detail="Invalid category")

    # Identify client (userId + IP)
    client_ip = request.client.host
    user_key = f"{data.userId}:{client_ip}"

    allowed, retry_after = check_rate_limit(user_key)

    if not allowed:
        logging.warning(f"Rate limit exceeded for {user_key}")

        return JSONResponse(
            status_code=429,
            content={
                "blocked": True,
                "reason": "Rate limit exceeded",
                "confidence": 0.99
            },
            headers={
                "Retry-After": str(retry_after)
            }
        )

    # If allowed
    logging.info(f"Request allowed for {user_key}")

    return {
        "blocked": False,
        "reason": "Input passed all security checks",
        "sanitizedOutput": data.input,
        "confidence": 0.95
    }
