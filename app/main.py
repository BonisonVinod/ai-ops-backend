from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}


# ✅ ONLY Batch 1 routers

from app.api.routes.health import router as health_router


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # keep open for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health_router)
