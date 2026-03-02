import os
import firebase_admin
from firebase_admin import credentials
from dotenv import load_dotenv

# ✅ Load .env FIRST before anything else
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import chat, documents, applications, schemes, webhook
from routers import telegram_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    cred_path = os.getenv("FIREBASE_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        try:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("✅ Successfully connected to Firebase!")
        except Exception as e:
            print(f"❌ Error initializing Firebase: {e}")
    else:
        print("⚠️ Firebase credentials not found.")
    yield


app = FastAPI(
    title="JanSahayak Backend",
    version="1.0.0",
    description="Backend services for JanSahayak (People's Helper).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telegram_webhook.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(applications.router)
app.include_router(schemes.router)
app.include_router(webhook.router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}