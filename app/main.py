from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

from app.api.routes.health import router as health_router
app.include_router(health_router)
