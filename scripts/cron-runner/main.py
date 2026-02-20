"""
Falcon-Eye Cron Runner
Executes a prompt against an agent via the main API, then reports status.
"""
import os
import sys
import httpx
from datetime import datetime, timezone

API_URL = os.getenv("API_URL", "http://falcon-eye-api:8000")
AGENT_ID = os.getenv("AGENT_ID", "")
CRON_JOB_ID = os.getenv("CRON_JOB_ID", "")
PROMPT = os.getenv("PROMPT", "")
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "120"))


def main():
    if not AGENT_ID or not PROMPT:
        print("ERROR: AGENT_ID and PROMPT are required")
        sys.exit(1)

    print(f"Cron runner: agent={AGENT_ID}, cron_job={CRON_JOB_ID}")
    print(f"Prompt: {PROMPT[:100]}...")

    status = "success"
    result_text = ""

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS + 10) as client:
            # Send prompt to agent
            res = client.post(
                f"{API_URL}/api/chat/{AGENT_ID}/send",
                json={"message": PROMPT, "source": "cron"},
            )
            if res.status_code == 200:
                data = res.json()
                result_text = data.get("response", "")[:500]
                print(f"Response: {result_text}")
            else:
                status = "error"
                result_text = f"API error ({res.status_code}): {res.text[:300]}"
                print(f"ERROR: {result_text}")

    except Exception as e:
        status = "error"
        result_text = str(e)[:500]
        print(f"ERROR: {e}")

    # Report status back to API
    if CRON_JOB_ID:
        try:
            with httpx.Client(timeout=10) as client:
                client.patch(
                    f"{API_URL}/api/cron/{CRON_JOB_ID}",
                    json={
                        "last_run": datetime.now(timezone.utc).isoformat(),
                        "last_result": result_text,
                        "last_status": status,
                    },
                )
                print(f"Reported status: {status}")
        except Exception as e:
            print(f"Failed to report status: {e}")

    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
