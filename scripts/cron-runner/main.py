"""
Falcon-Eye Cron Runner
Executes a prompt against an agent via the main API, then delivers
the response through the agent's configured channel (Telegram, etc.).
"""
import os
import sys
import httpx
from datetime import datetime, timezone

API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
AGENT_ID = os.getenv("AGENT_ID", "")
CRON_JOB_ID = os.getenv("CRON_JOB_ID", "")
PROMPT = os.getenv("PROMPT", "")
SESSION_ID = os.getenv("SESSION_ID", "")
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "120"))

TELEGRAM_API = "https://api.telegram.org"


def fetch_agent_config(client: httpx.Client) -> dict:
    """Fetch agent config from the main API."""
    try:
        res = client.get(f"{API_URL}/api/agents/{AGENT_ID}")
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Failed to fetch agent config: {e}")
    return {}


def deliver_telegram(client: httpx.Client, bot_token: str, chat_id: int, text: str, media: list[dict] | None = None):
    """Send the response (text + optional media) to a Telegram chat."""
    base = f"{TELEGRAM_API}/bot{bot_token}"

    if text:
        for i in range(0, len(text), 4000):
            chunk = text[i:i + 4000]
            try:
                res = client.post(f"{base}/sendMessage", json={"chat_id": chat_id, "text": chunk})
                if res.status_code != 200:
                    print(f"Telegram sendMessage error: {res.text[:300]}")
            except Exception as e:
                print(f"Telegram sendMessage failed: {e}")

    for item in (media or []):
        deliver_telegram_media(client, base, chat_id, item)


def deliver_telegram_media(client: httpx.Client, base_url: str, chat_id: int, item: dict):
    """Download a file from the agent filesystem and send it to Telegram."""
    file_path = item.get("path", "")
    caption = item.get("caption", "")
    media_type = item.get("media_type", "document")

    try:
        file_res = client.get(f"{API_URL}/api/files/read/{file_path}")
        if file_res.status_code != 200:
            print(f"Failed to download {file_path}: {file_res.status_code}")
            return

        content_type = file_res.headers.get("content-type", "")
        if "application/json" in content_type:
            data = file_res.json()
            if "content" in data:
                file_bytes = data["content"].encode("utf-8")
            else:
                print(f"No binary content for {file_path}")
                return
        else:
            file_bytes = file_res.content

        filename = os.path.basename(file_path)
        files = {}
        params = {"chat_id": str(chat_id)}
        if caption:
            params["caption"] = caption

        if media_type == "photo":
            endpoint = f"{base_url}/sendPhoto"
            files = {"photo": (filename, file_bytes)}
        elif media_type == "video":
            endpoint = f"{base_url}/sendVideo"
            files = {"video": (filename, file_bytes)}
        else:
            endpoint = f"{base_url}/sendDocument"
            files = {"document": (filename, file_bytes)}

        res = client.post(endpoint, data=params, files=files)
        if res.status_code == 200:
            print(f"Sent media: {file_path} ({media_type})")
        else:
            print(f"Telegram media send error: {res.text[:300]}")

    except Exception as e:
        print(f"Failed to send media {file_path}: {e}")


def main():
    if not AGENT_ID or not PROMPT:
        print("ERROR: AGENT_ID and PROMPT are required")
        sys.exit(1)

    print(f"Cron runner: agent={AGENT_ID}, cron_job={CRON_JOB_ID}")
    print(f"Prompt: {PROMPT[:100]}...")

    status = "success"
    result_text = ""
    media = []

    with httpx.Client(timeout=TIMEOUT_SECONDS + 10) as client:
        # 1. Send prompt to agent
        try:
            payload = {"message": PROMPT, "source": "cron"}
            if SESSION_ID:
                payload["session_id"] = SESSION_ID
            res = client.post(
                f"{API_URL}/api/chat/{AGENT_ID}/send",
                json=payload,
            )
            if res.status_code == 200:
                data = res.json()
                result_text = data.get("response", "")
                media = data.get("media", [])
                print(f"Response: {result_text[:200]}...")
            else:
                status = "error"
                result_text = f"API error ({res.status_code}): {res.text[:300]}"
                print(f"ERROR: {result_text}")
        except Exception as e:
            status = "error"
            result_text = str(e)[:500]
            print(f"ERROR: {e}")

        # 2. Deliver response via Telegram if the agent has a Telegram channel
        if result_text and status == "success":
            agent_config = fetch_agent_config(client)
            channel_type = agent_config.get("channel_type")
            channel_config = agent_config.get("channel_config") or {}

            if channel_type == "telegram":
                bot_token = channel_config.get("bot_token")
                chat_id = channel_config.get("chat_id")
                if bot_token and chat_id:
                    print(f"Delivering to Telegram chat_id={chat_id}")
                    deliver_telegram(client, bot_token, chat_id, result_text, media)
                elif not chat_id:
                    print("Telegram delivery skipped — no chat_id yet (send a message to the bot first)")

        # 3. Report status back to API
        if CRON_JOB_ID:
            try:
                client.patch(
                    f"{API_URL}/api/cron/{CRON_JOB_ID}",
                    json={
                        "last_run": datetime.now(timezone.utc).isoformat(),
                        "last_result": result_text[:500],
                        "last_status": status,
                    },
                )
                print(f"Reported status: {status}")
            except Exception as e:
                print(f"Failed to report status: {e}")

    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
