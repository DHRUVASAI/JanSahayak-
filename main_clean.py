import os
import firebase_admin
from firebase_admin import credentials
from dotenv import load_dotenv

from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import chat, documents, applications, schemes, webhook
from routers import telegram_webhook
from routers import whatsapp_webhook
from routers import rpa_queue
from routers import rpa


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not firebase_admin._apps:
        cred_path = os.getenv("FIREBASE_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            try:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                print("Successfully connected to Firebase!")
            except Exception as e:
                print(f"Error initializing Firebase: {e}")
        else:
            print("Warning: Firebase credentials not found.")
    else:
        print("Firebase already initialized (by router import)")
    yield


app = FastAPI(
    title="JanSahayak Backend",
    version="1.0.0",
    description="Backend services for JanSahayak (People's Helper).",
    lifespan=lifespan,
)

import os as _os
_os.makedirs("static", exist_ok=True)
_os.makedirs("mock_portal", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/mock_portal", StaticFiles(directory="mock_portal"), name="mock_portal")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telegram_webhook.router)
app.include_router(whatsapp_webhook.router)
app.include_router(rpa_queue.router)
app.include_router(rpa.router)
app.include_router(documents.router)
app.include_router(applications.router)
app.include_router(schemes.router)
app.include_router(webhook.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
