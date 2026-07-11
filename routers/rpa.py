import asyncio
import uuid
import os
import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/rpa", tags=["rpa"])

_job_queue = []
_results = {}

class JobResult(BaseModel):
    job_id: str
    success: bool
    reference: Optional[str] = None
    error: Optional[str] = None
    chat_id: Optional[int] = None

def enqueue_job(chat_id: int, scheme: str, user_data: dict) -> str:
    job_id = str(uuid.uuid4())[:8]
    _job_queue.append({"job_id": job_id, "chat_id": chat_id, "scheme": scheme, "user_data": user_data})
    print(f"[RPA QUEUE] Job {job_id} enqueued scheme={scheme}")
    return job_id

@router.get("/get-job")
async def get_job():
    if _job_queue:
        job = _job_queue.pop(0)
        print(f"[RPA] Dispatching job {job['job_id']}")
        return JSONResponse(job)
    return JSONResponse({})

@router.post("/complete-job")
async def complete_job(result: JobResult):
    print(f"[RPA] Complete: job={result.job_id} success={result.success} ref={result.reference}")
    if result.chat_id:
        asyncio.create_task(_notify(result))
    return {"ok": True}

async def _notify(result: JobResult):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    if result.success:
        ref = result.reference or "REF-DEMO"
        text = (
            "✅ <b>Form Filled Successfully!</b>\n\n"
            f"🎫 Reference ID: <code>{ref}</code>\n"
            "🤖 Chrome filled the form live on operator screen\n"
            "📱 SMS confirmation will be sent to your mobile\n"
            "📋 Save your Reference ID for tracking"
        )
    else:
        text = f"❌ RPA failed: {result.error or 'Unknown error'}"
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": result.chat_id, "text": text, "parse_mode": "HTML"}
        )
