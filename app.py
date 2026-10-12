import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from telethon import TelegramClient
from dotenv import load_dotenv
from subscription import subscription_url
from sessions import session_path_from_env


load_dotenv()
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "happvpn")
SESSION_FILE = session_path_from_env(os.getenv("TELEGRAM_SESSION_FILE", "telegram.session"))

client = TelegramClient(SESSION_FILE, API_ID, API_HASH)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized; create and upload a session file.")
    yield
    await client.disconnect()


app = FastAPI(title="HappiVPN subscription relay", lifespan=lifespan)


async def current_subscription_url() -> str:
    try:
        messages = await client.get_messages(CHANNEL, limit=20)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not read the Telegram channel.") from exc

    for message in messages:
        if not message or not message.text:
            continue
        url = subscription_url(message)
        if url:
            return url
    raise HTTPException(status_code=404, detail="No subscription URL found in the latest channel posts.")


async def serve_subscription(request: Request) -> Response:
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Content-Disposition": 'inline; filename="sub.txt"',
    }
    # Render's health probe uses HEAD. Respond without making a Telegram call.
    if request.method == "HEAD":
        return Response(status_code=200, media_type="text/plain", headers=headers)

    url = await current_subscription_url()
    return Response(content=url, media_type="text/plain", headers=headers)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def latest_subscription(request: Request):
    return await serve_subscription(request)


@app.api_route("/sub.txt", methods=["GET", "HEAD"], include_in_schema=False)
async def subscription_file(request: Request):
    return await serve_subscription(request)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"
