from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def getHealth():
    return {"health": "ok"}

