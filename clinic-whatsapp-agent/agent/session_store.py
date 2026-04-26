"""
In-memory session store with optional Redis backend.
Falls back to in-memory dict if Redis is not configured.
"""
import json
import os
from datetime import datetime
from typing import Optional

from .models import ConversationSession, ConversationStage, PatientProfile, UrgencyLevel

_sessions: dict[str, ConversationSession] = {}

try:
    import redis.asyncio as aioredis
    _redis_url = os.getenv("REDIS_URL")
    _redis: Optional[aioredis.Redis] = aioredis.from_url(_redis_url) if _redis_url else None
except ImportError:
    _redis = None

TTL_SECONDS = 60 * 60 * 24  # 24 hours


def _session_key(phone: str) -> str:
    return f"clinic:session:{phone}"


def _serialize(session: ConversationSession) -> str:
    data = {
        "phone": session.phone,
        "stage": session.stage.value,
        "messages": session.messages,
        "available_slots": session.available_slots,
        "selected_slot": session.selected_slot,
        "language": session.language,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "patient": {
            "phone": session.patient.phone,
            "name": session.patient.name,
            "problem_description": session.patient.problem_description,
            "treatment_type": session.patient.treatment_type,
            "specialty_needed": session.patient.specialty_needed,
            "duration_of_problem": session.patient.duration_of_problem,
            "previous_treatments": session.patient.previous_treatments,
            "urgency": session.patient.urgency.value,
            "latitude": session.patient.latitude,
            "longitude": session.patient.longitude,
            "city": session.patient.city,
            "qualifies": session.patient.qualifies,
            "disqualification_reason": session.patient.disqualification_reason,
        },
    }
    return json.dumps(data)


def _deserialize(raw: str) -> ConversationSession:
    data = json.loads(raw)
    p_data = data["patient"]
    patient = PatientProfile(
        phone=p_data["phone"],
        name=p_data.get("name"),
        problem_description=p_data.get("problem_description"),
        treatment_type=p_data.get("treatment_type"),
        specialty_needed=p_data.get("specialty_needed"),
        duration_of_problem=p_data.get("duration_of_problem"),
        previous_treatments=p_data.get("previous_treatments"),
        urgency=UrgencyLevel(p_data.get("urgency", "medium")),
        latitude=p_data.get("latitude"),
        longitude=p_data.get("longitude"),
        city=p_data.get("city"),
        qualifies=p_data.get("qualifies"),
        disqualification_reason=p_data.get("disqualification_reason"),
    )
    session = ConversationSession(phone=data["phone"])
    session.stage = ConversationStage(data["stage"])
    session.messages = data.get("messages", [])
    session.available_slots = data.get("available_slots", [])
    session.selected_slot = data.get("selected_slot")
    session.language = data.get("language", "es")
    session.patient = patient
    session.created_at = datetime.fromisoformat(data["created_at"])
    session.updated_at = datetime.fromisoformat(data["updated_at"])
    return session


async def get_session(phone: str) -> ConversationSession:
    """Retrieve or create a session for the given phone number."""
    if _redis:
        raw = await _redis.get(_session_key(phone))
        if raw:
            return _deserialize(raw)
    elif phone in _sessions:
        return _sessions[phone]

    session = ConversationSession(phone=phone)
    session.patient = PatientProfile(phone=phone)
    return session


async def save_session(session: ConversationSession):
    """Persist session to Redis or in-memory store."""
    if _redis:
        await _redis.setex(_session_key(session.phone), TTL_SECONDS, _serialize(session))
    else:
        _sessions[session.phone] = session


async def delete_session(phone: str):
    if _redis:
        await _redis.delete(_session_key(phone))
    elif phone in _sessions:
        del _sessions[phone]


async def list_active_sessions() -> list[dict]:
    """Return summary of active sessions (for dashboard)."""
    if _redis:
        keys = await _redis.keys("clinic:session:*")
        sessions = []
        for key in keys:
            raw = await _redis.get(key)
            if raw:
                s = _deserialize(raw)
                sessions.append(s.to_dict())
        return sessions
    return [s.to_dict() for s in _sessions.values()]
