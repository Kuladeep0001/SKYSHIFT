
from fastapi import FastAPI

from backend.routes.verification import router as verification_router

app = FastAPI(
    title="Planet X & SPHEREx API",
    description="Backend API for SPHEREx image analysis and candidate verification",
    version="1.0.0"
)


@app.get("/api/health")
async def health_check():
    return {
        "success": True,
        "data": {
            "status": "ok"
        },
        "error": None
    }


app.include_router(verification_router)
