# Telegram subscription relay

The Render service reads recent posts from `@happvpn` on every VPN-client refresh, finds the HTTPS `.../exec?url=...` subscription link, and responds with an HTTP redirect to that link. It ignores the `happ://` key and Telegram proxy links. The endpoint is `/`.

## Create the Telegram session on your computer

1. Install Python 3.10 or newer and run `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env`, then fill in your Telegram API ID and API hash (the Telegram user API hash, not a bot token). Both scripts load `.env` automatically.
3. Run `python login.py`. Enter the phone number and the code Telegram sends; enter the two-step verification password if requested. This creates `telegram.session`.
4. Keep the session file private. It grants access to your Telegram account. Do not commit or share it.

## Check the setup and save the current link

After creating the session, run `python check_channel.py`. It checks Telegram authorization and channel access, then writes the first matching current subscription URL to `latest_subscription_url.txt` in the project folder.

## Deploy on Render

Create a Render Web Service from this repository using `render.yaml`. Set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in the service environment. Add the generated `telegram.session` as a Render Secret File with the exact filename `telegram.session`; Render mounts it at `/etc/secrets/telegram.session` as configured. Deploy, then use `https://YOUR-SERVICE.onrender.com/` as the subscription URL in the VPN client.

Each client refresh causes a new Telegram lookup, so the next refresh picks up the newest matching post. Render's free service can sleep while idle; the first request after sleep may take longer. If the channel changes its post format or stops including an HTTPS `/exec?url=` link, the endpoint returns 404 until the format is adjusted.
