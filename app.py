import asyncio
import base64
import os
import re
import time
from contextlib import asynccontextmanager

import httpx
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

# Метаданные профиля для Happ. Для JSON-подписки их можно передать только HTTP-заголовками.
# Значения можно переопределить переменными окружения в Render. Пустое значение = не отправлять.
PROFILE_TITLE = os.getenv("PROFILE_TITLE", "SaS")                       # Happ режет до 25 символов
PROFILE_ANNOUNCE = os.getenv("PROFILE_ANNOUNCE", "🔒 Быстрый и стабильный VPN")  # до 200 символов
PROFILE_UPDATE_INTERVAL = os.getenv("PROFILE_UPDATE_INTERVAL", "1")     # часы
SUPPORT_URL = os.getenv("SUPPORT_URL", "")
WEB_PAGE_URL = os.getenv("WEB_PAGE_URL", "")


def _b64(text: str) -> str:
    """HTTP-заголовки только latin-1, поэтому кириллицу и эмодзи отдаём как base64:..."""
    return "base64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


URL_CACHE_TTL = 60          # сколько секунд помнить ссылку из Telegram
MAX_HOPS = 3                # сколько раз можно "пройти по ссылке в теле ответа"
SINGLE_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)

# Заголовки клиента, которые стоит передать апстриму (лимит устройств, формат под клиента)
FORWARD_REQUEST_HEADERS = (
    "user-agent", "x-hwid", "x-device-os", "x-ver-os", "x-device-model", "accept-language",
)
# Заголовки ответа, которые НЕ копируем (их пересчитает сервер сам)
SKIP_RESPONSE_HEADERS = {
    "content-length", "content-encoding", "transfer-encoding", "connection",
    "keep-alive", "set-cookie", "server", "date", "strict-transport-security",
}

client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
http: httpx.AsyncClient | None = None

_url_cache: dict = {"url": None, "ts": 0.0}
_url_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global http
    http = httpx.AsyncClient(follow_redirects=True, timeout=20.0)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized; create and upload a session file.")
    yield
    await client.disconnect()
    await http.aclose()


app = FastAPI(title="HappiVPN subscription relay", lifespan=lifespan)


async def _read_url_from_telegram() -> str:
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


async def current_subscription_url() -> str:
    """Ссылка из канала с кешем и блокировкой (чтобы не долбить Telegram)."""
    now = time.monotonic()
    if _url_cache["url"] and now - _url_cache["ts"] < URL_CACHE_TTL:
        return _url_cache["url"]

    async with _url_lock:
        now = time.monotonic()
        if _url_cache["url"] and now - _url_cache["ts"] < URL_CACHE_TTL:
            return _url_cache["url"]
        try:
            url = await _read_url_from_telegram()
        except HTTPException:
            # Telegram недоступен / формат поста изменился — отдаём последнюю рабочую ссылку
            if _url_cache["url"]:
                return _url_cache["url"]
            raise
        _url_cache.update(url=url, ts=time.monotonic())
        return url


async def fetch_subscription(url: str, request: Request) -> httpx.Response:
    """Переходит по ссылке и, если в ответе снова одна ссылка, идёт по ней дальше."""
    assert http is not None
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQUEST_HEADERS}

    for _ in range(MAX_HOPS):
        try:
            resp = await http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Could not fetch the subscription.") from exc

        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Subscription server returned {resp.status_code}.")

        body = resp.text.strip()
        if SINGLE_URL.match(body):
            url = body  # в ответе лежит ещё одна ссылка — идём по ней
            continue
        return resp

    raise HTTPException(status_code=502, detail="Too many nested subscription links.")


async def serve_subscription(request: Request) -> Response:
    # Render health probe использует HEAD. Отвечаем без обращений наружу.
    if request.method == "HEAD":
        return Response(status_code=200, media_type="text/plain")

    url = await current_subscription_url()
    upstream = await fetch_subscription(url, request)

    # Все имена в нижнем регистре, иначе наши заголовки и заголовки апстрима
    # дублируются (например, два Content-Disposition) и браузер/Happ отбрасывают ответ.
    headers = {
        k.lower(): v for k, v in upstream.headers.items() if k.lower() not in SKIP_RESPONSE_HEADERS
    }
    # subscription-userinfo, profile-title, profile-update-interval, routing и т.п.
    # остаются в headers и уходят клиенту как есть.
    # Свои метаданные профиля перекрывают апстримовские (иначе в Happ останется имя хоста)
    for key in ("profile-title", "announce", "profile-update-interval", "support-url", "profile-web-page-url"):
        headers.pop(key, None)
    if PROFILE_TITLE:
        headers["profile-title"] = _b64(PROFILE_TITLE)
    if PROFILE_ANNOUNCE:
        headers["announce"] = _b64(PROFILE_ANNOUNCE)
    if PROFILE_UPDATE_INTERVAL:
        headers["profile-update-interval"] = PROFILE_UPDATE_INTERVAL
    if SUPPORT_URL:
        headers["support-url"] = SUPPORT_URL
    if WEB_PAGE_URL:
        headers["profile-web-page-url"] = WEB_PAGE_URL
    headers["cache-control"] = "no-store, no-cache, must-revalidate"
    headers.setdefault("content-disposition", 'inline; filename="sub.txt"')

    return Response(
        content=upstream.content,
        media_type="text/plain",
        headers=headers,
    )


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def latest_subscription(request: Request):
    return await serve_subscription(request)


@app.api_route("/sub.txt", methods=["GET", "HEAD"], include_in_schema=False)
async def subscription_file(request: Request):
    return await serve_subscription(request)


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"
