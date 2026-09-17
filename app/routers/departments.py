from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.scheduler import list_department_names

router = APIRouter(prefix="/api/v1", tags=["departments"])


@router.get("/departments")
async def get_departments(db: AsyncSession = Depends(get_db)):
    return {"departments": await list_department_names(db)}
