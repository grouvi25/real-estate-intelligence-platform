"""Owner administration API. TZ sections 3, 17, 30."""
import uuid
from typing import Literal, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager, require_owner
from app.exceptions import NotFoundError
from app.models.manager import Manager

router = APIRouter()

class ManagerUpdate(BaseModel):
    role: Optional[Literal["manager", "admin", "owner"]] = None
    is_active: Optional[bool] = None

def dto(m):
    return {"id": str(m.id), "name": m.name, "role": m.role, "is_active": m.is_active,
            "telegram_id": m.telegram_id, "max_user_id": m.max_user_id}

@router.get("/managers")
async def managers(current: CurrentManager = Depends(get_current_manager), session=Depends(get_session)):
    await require_owner(session, current)
    rows=(await session.execute(select(Manager).where(Manager.agency_id==uuid.UUID(current.agency_id)).order_by(Manager.created_at))).scalars().all()
    return {"managers": [dto(m) for m in rows]}

@router.patch("/managers/{manager_id}")
async def update_manager(manager_id: uuid.UUID, req: ManagerUpdate, current: CurrentManager = Depends(get_current_manager), session=Depends(get_session)):
    await require_owner(session, current)
    m=await session.get(Manager, manager_id)
    if m is None or str(m.agency_id) != current.agency_id:
        raise NotFoundError("Manager", str(manager_id))
    if req.role is not None:
        m.role = req.role
    if req.is_active is not None:
        m.is_active = req.is_active
    await session.commit()
    return dto(m)
