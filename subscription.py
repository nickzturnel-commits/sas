import re
from urllib.parse import parse_qs, urlparse


def message_urls(message) -> list[str]:
    urls = re.findall(r"https?://[^\s<>\])}]+", message.text or "", flags=re.IGNORECASE)
    for entity in message.entities or []:
        url = getattr(entity, "url", None)
        if url:
            urls.append(url)
    # Telegram posts sometimes place Markdown fences or escaped punctuation
    # directly after a URL. Remove those suffix characters from both text and
    # hidden-link entities before returning the subscription URL.
    cleaned = (url.rstrip(".,;!?\\`") for url in urls)
    return list(dict.fromkeys(cleaned))


def subscription_url(message) -> str | None:
    for url in message_urls(message):
        try:
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
        except ValueError:
            continue
        if parsed.scheme == "https" and parsed.netloc and parsed.path.rstrip("/").endswith("/exec") and query.get("url"):
            return url
    return None
