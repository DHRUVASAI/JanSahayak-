from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/schemes", tags=["schemes"])


@router.get("/list")
async def list_schemes():
    """
    List all supported government schemes.
    REQ-DATA-006, REQ-SUCCESS-015.
    """
    return {"schemes": []}


@router.get("/{scheme_id}")
async def get_scheme(scheme_id: str):
    """
    Get scheme details.
    REQ-DATA-006, REQ-DATA-009.
    """
    return {"schemeId": scheme_id, "details": None}


@router.post("/eligibility")
async def check_eligibility():
    """
    Check user eligibility for a scheme.
    REQ-DATA-010, REQ-NLU-001.
    """
    return {"eligible": False, "reason": "stub"}


@router.get("/search")
async def search_schemes(q: str | None = None):
    """
    Search schemes by keyword.
    REQ-DATA-010, REQ-SUCCESS-015.
    """
    return {"query": q, "results": []}


@router.get("/recommendations/{user_id}")
async def scheme_recommendations(user_id: str):
    """
    Recommend schemes for a user.
    REQ-DATA-010, REQ-SUCCESS-015.
    """
    return {"userId": user_id, "recommendations": []}

