from typing import Optional, List

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """
    Generic chat message schema.
    REQ-UI-001, REQ-INT-001, REQ-NLU-001.
    """

    userId: Optional[str] = None
    sessionId: Optional[str] = None
    text: Optional[str] = ""
    language: Optional[str] = "auto"
    channel: Optional[str] = "whatsapp"  # e.g., "whatsapp", "android", "web"
    history: Optional[List[dict]] = []

