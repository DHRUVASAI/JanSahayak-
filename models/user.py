from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class BhashiniProfile(BaseModel):
    primaryLanguage: Optional[str] = None
    dialectPreference: Optional[str] = None
    voiceSettings: Optional[dict] = None


class Location(BaseModel):
    state: Optional[str] = None
    district: Optional[str] = None
    pincode: Optional[str] = None


class Demographics(BaseModel):
    age: Optional[int] = None
    gender: Optional[str] = None
    category: Optional[str] = None
    income: Optional[float] = None


class UserProfile(BaseModel):
    """
    User profile schema aligned with Firestore document.
    REQ-DATA-001, REQ-DATA-002, REQ-ARCH-006.
    """

    userId: str
    phoneNumber: str
    preferredLanguage: Optional[str] = None
    bhashiniProfile: Optional[BhashiniProfile] = None
    location: Optional[Location] = None
    demographics: Optional[Demographics] = None
    documents: List[str] = []
    applications: List[str] = []
    firebaseAuth: Optional[str] = None
    createdAt: Optional[datetime] = None
    lastActive: Optional[datetime] = None

