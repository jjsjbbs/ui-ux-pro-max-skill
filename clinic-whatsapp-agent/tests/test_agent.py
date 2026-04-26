"""
Unit tests for clinic agent — run with: pytest tests/
Requires ANTHROPIC_API_KEY in environment for integration tests.
"""
import asyncio
import os
import pytest

from agent.models import ConversationSession, ConversationStage, PatientProfile, UrgencyLevel
from agent.geolocation import haversine_km, find_nearest_clinics, parse_whatsapp_location
from agent.clinic_config import load_clinic_config, get_available_slots
from agent.session_store import get_session, save_session, delete_session


# ── Geolocation tests ─────────────────────────────────────────────────────────

def test_haversine_same_point():
    assert haversine_km(19.43, -99.13, 19.43, -99.13) == 0.0


def test_haversine_known_distance():
    # CDMX to Guadalajara ~460 km
    dist = haversine_km(19.4326, -99.1332, 20.6597, -103.3496)
    assert 450 < dist < 480


def test_parse_location_from_params():
    coords = parse_whatsapp_location("", "19.4326", "-99.1332")
    assert coords == (19.4326, -99.1332)


def test_parse_location_from_text():
    coords = parse_whatsapp_location("Mi ubicación es 19.4326,-99.1332", None, None)
    assert coords is not None
    assert abs(coords[0] - 19.4326) < 0.001


def test_find_nearest_clinics():
    cfg = load_clinic_config()
    results = find_nearest_clinics(19.4326, -99.1332, cfg.locations, max_distance_km=100)
    assert isinstance(results, list)


# ── Clinic config tests ───────────────────────────────────────────────────────

def test_load_demo_config():
    cfg = load_clinic_config()
    assert cfg.name
    assert cfg.type
    assert len(cfg.locations) >= 1


def test_get_available_slots():
    cfg = load_clinic_config()
    loc = cfg.locations[0]
    slots = get_available_slots(loc, loc.specialties[0] if loc.specialties else "Medicina General")
    assert isinstance(slots, list)
    if slots:
        s = slots[0]
        assert "slot_id" in s
        assert "date" in s
        assert "time" in s
        assert "doctor_name" in s


# ── Session store tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_create_and_retrieve():
    phone = "+test_pytest_001"
    session = await get_session(phone)
    assert session.phone == phone
    assert session.stage == ConversationStage.WELCOME


@pytest.mark.asyncio
async def test_session_save_and_load():
    phone = "+test_pytest_002"
    session = await get_session(phone)
    session.patient.name = "Test Paciente"
    session.stage = ConversationStage.QUALIFY_PROBLEM
    await save_session(session)

    loaded = await get_session(phone)
    assert loaded.patient.name == "Test Paciente"
    assert loaded.stage == ConversationStage.QUALIFY_PROBLEM

    await delete_session(phone)


# ── Model tests ───────────────────────────────────────────────────────────────

def test_session_to_dict():
    session = ConversationSession(phone="+52test")
    session.patient = PatientProfile(phone="+52test", name="Juan")
    session.add_message("user", "Hola")
    session.add_message("assistant", "¡Hola! ¿En qué puedo ayudarte?")

    d = session.to_dict()
    assert d["phone"] == "+52test"
    assert d["messages_count"] == 2
    assert d["patient"]["name"] == "Juan"


def test_emergency_keyword_detection():
    """Verify emergency keywords are covered."""
    from agent.agent import ClinicAgent
    # We test the method without full init
    emergency_words = ["infarto", "no puedo respirar", "paro cardíaco", "desmayé"]
    from agent.agent import EMERGENCY_KEYWORDS
    for word in emergency_words:
        found = any(kw in word.lower() for kw in EMERGENCY_KEYWORDS)
        assert found, f"'{word}' not detected as emergency"
