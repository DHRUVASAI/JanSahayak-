"""
routers/memory.py
Firebase Firestore conversation memory.
Saves and retrieves last N messages per user (WhatsApp number).
"""
import os
from datetime import datetime, timezone
from typing import List, Dict

# Firebase is initialised in main.py — import the already-initialised client
try:
    from google.cloud import firestore as _firestore
    import firebase_admin
    from firebase_admin import firestore

    def _db():
        return firestore.client()

    FIREBASE_AVAILABLE = True
except Exception as e:
    print(f"[MEMORY] Firebase not available: {e}")
    FIREBASE_AVAILABLE = False

# In-memory fallback when Firebase is unavailable
_IN_MEMORY: Dict[str, list] = {}


async def save_message(user_id: str, role: str, content: str) -> None:
    """
    Save a single message to Firestore under:
      conversations/{user_id}/messages/{auto-id}
    """
    entry = {
        "role": role,           # "user" or "assistant"
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            db.collection("conversations") \
              .document(user_id) \
              .collection("messages") \
              .add(entry)
            return
        except Exception as e:
            print(f"[MEMORY] Firestore save error: {e}")

    # In-memory fallback
    if user_id not in _IN_MEMORY:
        _IN_MEMORY[user_id] = []
    _IN_MEMORY[user_id].append(entry)
    # Keep only last 50 in memory to avoid unbounded growth
    _IN_MEMORY[user_id] = _IN_MEMORY[user_id][-50:]


async def get_history(user_id: str, limit: int = 10) -> List[dict]:
    """
    Retrieve last `limit` messages for a user, ordered oldest→newest.
    Returns list of {"role": ..., "content": ...} dicts.
    """
    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            docs = (
                db.collection("conversations")
                  .document(user_id)
                  .collection("messages")
                  .order_by("timestamp", direction="DESCENDING")
                  .limit(limit)
                  .stream()
            )
            messages = [doc.to_dict() for doc in docs]
            # Reverse so oldest is first (chronological order for prompt)
            messages.reverse()
            return [{"role": m["role"], "content": m["content"]} for m in messages]
        except Exception as e:
            print(f"[MEMORY] Firestore read error: {e}")

    # In-memory fallback
    msgs = _IN_MEMORY.get(user_id, [])
    return [{"role": m["role"], "content": m["content"]} for m in msgs[-limit:]]


async def save_application(application_id: str, user_data: dict, scheme: str = "PM-KISAN") -> None:
    """
    Save application to Firestore under:
      applications/{application_id}
    """
    entry = {
        "application_id": application_id,
        "scheme": scheme,
        "user_data": user_data,
        "status": "Under Review",
        "submission_date": datetime.now(timezone.utc).isoformat(),
        "name": user_data.get("name", ""),
    }

    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            db.collection("applications").document(application_id).set(entry)
            print(f"[MEMORY] Saved application {application_id}")
            return
        except Exception as e:
            print(f"[MEMORY] Firestore application save error: {e}")

    # In-memory fallback
    print(f"[MEMORY] Application {application_id} saved to memory fallback")


async def get_application_status(application_id: str) -> dict:
    """
    Retrieve application status from Firestore.
    Returns dict with application details or empty dict if not found.
    """
    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            doc = db.collection("applications").document(application_id).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"[MEMORY] Firestore application read error: {e}")

    # In-memory fallback - return empty for now
    return {}


async def save_scheme_state(user_id: str, scheme: str) -> None:
    """
    Save the current scheme state for a user to Firestore.
    """
    entry = {
        "scheme": scheme,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            db.collection("user_states").document(user_id).set(entry)
            print(f"[MEMORY] Saved scheme state {scheme} for {user_id}")
            return
        except Exception as e:
            print(f"[MEMORY] Firestore scheme state save error: {e}")

    # In-memory fallback
    if "user_states" not in _IN_MEMORY:
        _IN_MEMORY["user_states"] = {}
    _IN_MEMORY["user_states"][user_id] = entry
    print(f"[MEMORY] Scheme state {scheme} for {user_id} saved to memory fallback")


async def get_scheme_state(user_id: str) -> str:
    """
    Retrieve the current scheme state for a user.
    Returns scheme name or empty string if not found.
    """
    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            doc = db.collection("user_states").document(user_id).get()
            if doc.exists:
                return doc.to_dict().get("scheme", "")
        except Exception as e:
            print(f"[MEMORY] Firestore scheme state read error: {e}")

    # In-memory fallback
    if "user_states" in _IN_MEMORY and user_id in _IN_MEMORY["user_states"]:
        return _IN_MEMORY["user_states"][user_id].get("scheme", "")
    return ""


async def clear_history(user_id: str) -> None:
    """Delete all messages for a user (for session reset)."""
    if FIREBASE_AVAILABLE:
        try:
            db = _db()
            col = db.collection("conversations").document(user_id).collection("messages")
            for doc in col.stream():
                doc.reference.delete()
        except Exception as e:
            print(f"[MEMORY] Firestore clear error: {e}")

    _IN_MEMORY.pop(user_id, None)
