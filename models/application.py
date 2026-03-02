from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ApplicationRecord(BaseModel):
    """
    Application record schema aligned with Firestore document.
    REQ-GOV-011, REQ-DATA-006, REQ-ARCH-006.
    """

    applicationId: str
    userId: str
    schemeId: str
    status: str
    submissionDate: Optional[datetime] = None
    lastUpdated: Optional[datetime] = None
    documents: List[str] = []
    formData: Optional[dict] = None
    governmentRefId: Optional[str] = None
    receipt: Optional[str] = None

