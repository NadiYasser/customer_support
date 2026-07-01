"""WhatsApp channel adapter — Meta Cloud API (M13).

A *channel adapter* is the boundary translator between one transport (here,
WhatsApp's Graph API) and our channel-agnostic graph, which only ever speaks
`thread_id + message -> reply`. Everything WhatsApp-specific lives in this module;
the graph, agents, and tools never learn that WhatsApp exists. Same swappable-
boundary idea as repositories/, applied to the INPUT side.

Three responsibilities, matching the three things the Cloud API needs from us:

1. verify_webhook(...)  — the one-time GET handshake. Meta calls our webhook with
   hub.mode/hub.verify_token/hub.challenge; if the token matches the secret we
   configured, we echo the challenge back to prove we own the endpoint.
2. parse_inbound(body)  — dig the sender's phone + text out of Meta's deeply
   nested POST envelope. Returns None for non-message callbacks (delivery
   receipts, read receipts, status updates) which share the same webhook.
3. send_text(phone, text) — POST a reply to the Graph API. In MOCK mode (no
   credentials configured) it logs instead, so the flow runs locally.

Phone <-> thread_id: we key conversations by "wa:{phone}", so a given WhatsApp
number maps to one persistent LangGraph thread (its checkpointed history). The
"wa:" prefix also lets /resume tell channel threads apart from web ones.
"""
import requests

from app import config

THREAD_PREFIX = "wa:"


def thread_id_for(phone: str) -> str:
    """Map a sender's phone number to its stable conversation thread_id."""
    return f"{THREAD_PREFIX}{phone}"


def is_mock() -> bool:
    """True when outbound sends are logged instead of really hitting Meta.

    We're in mock mode whenever the credentials needed to POST a reply are
    missing — which is the default for local development.
    """
    return not (config.WHATSAPP_ACCESS_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def verify_webhook(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """Handle Meta's GET verification handshake.

    When you register a webhook, Meta sends a GET with hub.mode="subscribe",
    hub.verify_token=<the secret you typed into the Meta dashboard>, and a random
    hub.challenge. We must echo the challenge back VERBATIM, but only if the token
    matches the secret we configured — that match is what proves the request came
    from our app and not a random scanner. Returns the challenge to echo, or None
    if verification fails (the caller turns None into a 403).
    """
    if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
        return challenge
    return None


def parse_inbound(body: dict) -> tuple[str, str] | None:
    """Extract (phone, text) from a Meta webhook POST, or None if not a text message.

    The Cloud API wraps every callback in the same envelope shape:

        entry[0].changes[0].value.messages[0] = {
            "from": "<sender phone>",
            "type": "text",
            "text": {"body": "<the message>"},
            ...
        }

    The SAME webhook also receives non-message callbacks (delivery/read receipts,
    status updates) that have a `statuses` array instead of `messages`, plus
    non-text message types (images, audio). We only handle inbound TEXT here and
    return None for everything else, so the webhook can cleanly ignore them.
    """
    try:
        value = body["entry"][0]["changes"][0]["value"]
        messages = value.get("messages")
        if not messages:
            return None  # a status/receipt callback, not an inbound message
        message = messages[0]
        if message.get("type") != "text":
            return None  # image/audio/etc — out of scope for this learning build
        phone = message["from"]
        text = message["text"]["body"]
        return phone, text
    except (KeyError, IndexError, TypeError):
        # Malformed or unexpected shape: treat as "nothing to process" rather than
        # crashing the webhook — Meta retries on non-200s, so we must not 500 here.
        return None


def send_text(phone: str, text: str) -> None:
    """Send a WhatsApp text message to `phone` via the Graph API.

    In mock mode (no credentials) we log the outbound message instead of calling
    Meta, so the end-to-end flow is exercisable with no real account. The wire
    shape mirrors the Cloud API's "messages" endpoint exactly, so flipping to real
    mode is purely a matter of setting the env vars.
    """
    if is_mock():
        # print (not logger.info) so the outbound is ALWAYS visible in the server
        # console — under uvicorn a bare logger's INFO records get swallowed, and in
        # mock mode this line is the only evidence the customer "received" a reply.
        print(f"[whatsapp:mock] -> {phone}: {text}", flush=True)
        return

    url = (
        f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}"
        f"/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:
        # Log and swallow: a failed outbound send shouldn't bubble a 500 back to
        # Meta's webhook delivery (which would trigger retries of the INBOUND
        # message and re-run the graph). Surface the error for the operator.
        print(f"[whatsapp] send failed {resp.status_code}: {resp.text}", flush=True)
