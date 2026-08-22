import requests

LOGGING_SERVICE_URL = "http://localhost:5003"

def log_event(user_id: str, service: str, event_type: str, description: str):
    try:
        requests.post(
            f"{LOGGING_SERVICE_URL}/log-event",
            json={
                "user_id": user_id,
                "service": service,
                "event_type": event_type,
                "description": description,
            },
            timeout=3,
        )
    except requests.RequestException:
        pass  # logging should never crash the main service