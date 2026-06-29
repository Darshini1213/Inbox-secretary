import json
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("inbox-secretary-server")

DATA_FILE = "mock_inbox_data.json"

def _load_data():
    if not os.path.exists(DATA_FILE):
        default_data = {
            "emails": [
                {"id": 1, "sender": "manager@work.com", "subject": "Quarterly Report", "body": "Please review the quarterly report draft and reply with your comments."},
                {"id": 2, "sender": "friend@personal.com", "subject": "Dinner Next Week?", "body": "Are you free for dinner next Tuesday around 7 PM?"},
                {"id": 3, "sender": "promo@spam.com", "subject": "Buy Coins NOW!", "body": "Get 500% bonus coins when you deposit today!"}
            ],
            "calendar": []
        }
        with open(DATA_FILE, "w") as f:
            json.dump(default_data, f, indent=2)
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Recreate on corruption
            return {
                "emails": [
                    {"id": 1, "sender": "manager@work.com", "subject": "Quarterly Report", "body": "Please review the quarterly report draft and reply with your comments."},
                    {"id": 2, "sender": "friend@personal.com", "subject": "Dinner Next Week?", "body": "Are you free for dinner next Tuesday around 7 PM?"},
                    {"id": 3, "sender": "promo@spam.com", "subject": "Buy Coins NOW!", "body": "Get 500% bonus coins when you deposit today!"}
                ],
                "calendar": []
            }

def _save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

@mcp.tool()
def list_emails() -> str:
    """List mock emails in the user's inbox. Use this to inspect messages."""
    data = _load_data()
    return json.dumps(data["emails"], indent=2)

@mcp.tool()
def send_email_reply(email_id: int, reply_body: str) -> str:
    """Send an email reply to the specified email ID."""
    data = _load_data()
    emails = data["emails"]
    matched = [e for e in emails if e["id"] == email_id]
    if not matched:
        return f"Error: Email with ID {email_id} not found."
    
    # In a real app we would SMTP, here we log it
    print(f"SMTP SEND: Sent reply to {matched[0]['sender']}: {reply_body}")
    return f"Success: Email reply sent to {matched[0]['sender']}."

@mcp.tool()
def schedule_calendar_event(title: str, date_str: str, time_str: str, description: str = "") -> str:
    """Schedule a calendar event with a title, date, time, and optional description."""
    data = _load_data()
    event = {
        "title": title,
        "date": date_str,
        "time": time_str,
        "description": description
    }
    data["calendar"].append(event)
    _save_data(data)
    return f"Success: Calendar event '{title}' scheduled for {date_str} at {time_str}."

if __name__ == "__main__":
    mcp.run()
