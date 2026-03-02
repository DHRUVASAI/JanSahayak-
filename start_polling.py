import asyncio, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / ".env")
import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def poll():
    offset = 0
    print("Polling started...")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                r = await client.get(f"{TG_API}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=35)
                updates = r.json().get("result", [])
                for u in updates:
                    offset = u["update_id"] + 1
                    print(f"Update received: {u}")
                    await client.post("http://localhost:8080/telegram/webhook", json=u)
            except Exception as e:
                print(f"Poll error: {e}")
                await asyncio.sleep(3)

asyncio.run(poll())
