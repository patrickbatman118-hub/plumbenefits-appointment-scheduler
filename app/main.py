from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import departments, pipeline

app = FastAPI(title="AI-Powered Appointment Scheduler Assistant")

app.include_router(pipeline.router)
app.include_router(departments.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
