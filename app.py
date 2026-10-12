import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from telethon import TelegramClient
from dotenv import load_dotenv
from subscription import subscription_url


load_dotenv()
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
CHANNEL = os.getenv("TELEGRAM_CHANNEL", "happvpn")
SESSION_FILE = os.getenv("TELEGRAM_SESSION_FILE", "/etc/secrets/telegram.session")

client = TelegramClient(SESSION_FILE, API_ID, API_HASH)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized; create and upload a session file.")
    yield
    await client.disconnect()


app = FastAPI(title="HappiVPN subscription relay", lifespan=lifespan)


@app.get("/", include_in_schema=False)
async def latest_subscription():
    try:
        messages = await client.get_messages(CHANNEL, limit=20)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not read the Telegram channel.") from exc

    for message in messages:
        if not message or not message.text:
            continue
        url = subscription_url(message)
        if url:
            # VPN clients follow redirects and receive the channel's current
            # subscription URL on every refresh request.
            return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=404, detail="No subscription URL found in the latest channel posts.")


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"
