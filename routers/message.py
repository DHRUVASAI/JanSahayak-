"""
models/message.py
Pydantic models for JanSahayak chat messages.
"""
from typing import List, Optional
from pydantic import BaseModel


class ChatMessage(BaseModel):
    userId: Optional[str] = None
    text: Optional[str] = ""
    channel: Optional[str] = "whatsapp"   # "whatsapp" | "web"
    language: Optional[str] = "auto"
    history: Optional[List[dict]] = []    # Last N messages for memory context
