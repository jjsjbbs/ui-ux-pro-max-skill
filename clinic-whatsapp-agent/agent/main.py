"""
FastAPI server — Twilio WhatsApp webhook + admin dashboard API.
"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Form, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .agent import ClinicAgent
from .session_store import get_session, save_session, list_active_sessions, delete_session
from .models import ConversationStage

# Singleton agent (loads config + Anthropic client once)
_agent: Optional[ClinicAgent] = None


def get_agent() -> ClinicAgent:
    global _agent
    if _agent is None:
        _agent = ClinicAgent()
    return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up agent on startup
    get_agent()
    yield


app = FastAPI(
    title="Clinic WhatsApp Agent",
    description="AI-powered WhatsApp agent for clinics — qualifies patients and books appointments.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve dashboard static files if the folder exists
_dashboard_path = Path(__file__).parent.parent / "dashboard"
if _dashboard_path.exists():
    app.mount("/static", StaticFiles(directory=str(_dashboard_path)), name="static")


# ─── WhatsApp Webhook ──────────────────────────────────────────────────────────

@app.post("/webhook/whatsapp", response_class=PlainTextResponse)
async def whatsapp_webhook(
    request: Request,
    Body: str = Form(default=""),
    From: str = Form(default=""),
    Latitude: Optional[str] = Form(default=None),
    Longitude: Optional[str] = Form(default=None),
    agent: ClinicAgent = Depends(get_agent),
):
    """
    Twilio WhatsApp webhook endpoint.
    Receives messages and returns TwiML responses.
    """
    phone = From.strip()
    text = Body.strip()

    if not phone or not text:
        return _twiml_reply("")

    session = await get_session(phone)
    reply = await agent.process_message(session, text, Latitude, Longitude)
    await save_session(session)

    return _twiml_reply(reply)


def _twiml_reply(message: str) -> str:
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>"""


# ─── Test endpoint (for development without Twilio) ───────────────────────────

@app.post("/api/chat")
async def chat_api(request: Request, agent: ClinicAgent = Depends(get_agent)):
    """Development chat endpoint — simulates WhatsApp messages."""
    body = await request.json()
    phone = body.get("phone", "+test000000")
    text = body.get("message", "")
    lat = body.get("latitude")
    lon = body.get("longitude")

    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    session = await get_session(phone)
    reply = await agent.process_message(
        session, text,
        str(lat) if lat else None,
        str(lon) if lon else None,
    )
    await save_session(session)

    return {
        "reply": reply,
        "stage": session.stage.value,
        "patient": session.to_dict()["patient"],
    }


@app.delete("/api/chat/{phone}")
async def reset_chat(phone: str):
    """Reset conversation for a phone number."""
    await delete_session(phone)
    return {"status": "reset", "phone": phone}


# ─── Admin Dashboard API ───────────────────────────────────────────────────────

@app.get("/api/sessions")
async def get_sessions():
    sessions = await list_active_sessions()
    return {"sessions": sessions, "total": len(sessions)}


@app.get("/api/sessions/{phone}")
async def get_session_detail(phone: str):
    session = await get_session(phone)
    return {
        "session": session.to_dict(),
        "messages": session.messages,
        "available_slots": session.available_slots,
        "selected_slot": session.selected_slot,
    }


@app.get("/api/stats")
async def get_stats():
    sessions = await list_active_sessions()
    total = len(sessions)
    by_stage = {}
    qualified = 0
    disqualified = 0
    booked = 0

    for s in sessions:
        stage = s.get("stage", "unknown")
        by_stage[stage] = by_stage.get(stage, 0) + 1
        if s.get("patient", {}).get("qualifies") is True:
            qualified += 1
        if stage == ConversationStage.DISQUALIFIED.value:
            disqualified += 1
        if stage == ConversationStage.COMPLETED.value:
            booked += 1

    return {
        "total_conversations": total,
        "qualified": qualified,
        "disqualified": disqualified,
        "booked": booked,
        "conversion_rate": round(booked / total * 100, 1) if total > 0 else 0,
        "by_stage": by_stage,
    }


@app.get("/api/clinic")
async def get_clinic_info(agent: ClinicAgent = Depends(get_agent)):
    cfg = agent.config
    return {
        "name": cfg.name,
        "type": cfg.type,
        "tagline": cfg.tagline,
        "locations": [
            {
                "id": loc.id,
                "name": loc.name,
                "address": loc.address,
                "city": loc.city,
                "phone": loc.phone,
                "specialties": loc.specialties,
                "doctors": [{"name": d.name, "specialty": d.specialty} for d in loc.doctors],
            }
            for loc in cfg.locations
        ],
    }


# ─── Dashboard HTML ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    dashboard_file = Path(__file__).parent.parent / "dashboard" / "index.html"
    if dashboard_file.exists():
        return HTMLResponse(dashboard_file.read_text())
    return HTMLResponse("<h1>Clinic WhatsApp Agent</h1><p>Dashboard not found. See /docs</p>")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "clinic-whatsapp-agent"}
