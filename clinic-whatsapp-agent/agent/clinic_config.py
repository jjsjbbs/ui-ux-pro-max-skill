"""
Clinic configuration loader — reads from config/clinic.json or environment.
Supports any clinic type: dental, dermatology, orthopedics, aesthetics, etc.
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Optional


@dataclass
class DaySchedule:
    open: str   # "08:00"
    close: str  # "18:00"
    break_start: Optional[str] = None
    break_end: Optional[str] = None
    slot_duration_minutes: int = 30


@dataclass
class Doctor:
    id: str
    name: str
    specialty: str
    languages: list[str] = field(default_factory=lambda: ["es"])
    bio: Optional[str] = None


@dataclass
class ClinicLocation:
    id: str
    name: str
    address: str
    city: str
    phone: str
    whatsapp: str
    latitude: float
    longitude: float
    schedule: dict[str, DaySchedule] = field(default_factory=dict)
    doctors: list[Doctor] = field(default_factory=list)
    specialties: list[str] = field(default_factory=list)


@dataclass
class ClinicConfig:
    name: str
    type: str              # dental, dermatology, aesthetics, orthopedics, general, etc.
    tagline: str
    language: str          # default language: "es" or "en"
    locations: list[ClinicLocation] = field(default_factory=list)
    qualification_rules: dict = field(default_factory=dict)
    booking_url: Optional[str] = None
    calendar_api: Optional[str] = None


_CONFIG_PATH = Path(__file__).parent.parent / "config" / "clinic.json"
_cached_config: Optional[ClinicConfig] = None


def _parse_schedule(raw: dict) -> dict[str, DaySchedule]:
    days = {}
    for day, data in raw.items():
        if data.get("closed"):
            continue
        days[day] = DaySchedule(
            open=data["open"],
            close=data["close"],
            break_start=data.get("break_start"),
            break_end=data.get("break_end"),
            slot_duration_minutes=data.get("slot_duration_minutes", 30),
        )
    return days


def load_clinic_config() -> ClinicConfig:
    global _cached_config
    if _cached_config:
        return _cached_config

    config_path = Path(os.getenv("CLINIC_CONFIG_PATH", str(_CONFIG_PATH)))

    if not config_path.exists():
        # Return a demo config so the server starts without a config file
        return _demo_config()

    with open(config_path) as f:
        data = json.load(f)

    locations = []
    for loc in data.get("locations", []):
        doctors = [
            Doctor(
                id=d["id"],
                name=d["name"],
                specialty=d["specialty"],
                languages=d.get("languages", ["es"]),
                bio=d.get("bio"),
            )
            for d in loc.get("doctors", [])
        ]
        locations.append(
            ClinicLocation(
                id=loc["id"],
                name=loc["name"],
                address=loc["address"],
                city=loc["city"],
                phone=loc["phone"],
                whatsapp=loc["whatsapp"],
                latitude=loc["latitude"],
                longitude=loc["longitude"],
                schedule=_parse_schedule(loc.get("schedule", {})),
                doctors=doctors,
                specialties=loc.get("specialties", []),
            )
        )

    _cached_config = ClinicConfig(
        name=data["name"],
        type=data["type"],
        tagline=data.get("tagline", ""),
        language=data.get("language", "es"),
        locations=locations,
        qualification_rules=data.get("qualification_rules", {}),
        booking_url=data.get("booking_url"),
        calendar_api=data.get("calendar_api"),
    )
    return _cached_config


def get_available_slots(location: ClinicLocation, specialty: str, days_ahead: int = 7) -> list[dict]:
    """Generate available appointment slots for the next N days."""
    from datetime import date, timedelta
    import uuid

    slots = []
    today = date.today()
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    doctors = [d for d in location.doctors if d.specialty.lower() == specialty.lower()]
    if not doctors:
        doctors = location.doctors  # fallback: any doctor

    for i in range(1, days_ahead + 1):
        target_date = today + timedelta(days=i)
        day_name = day_names[target_date.weekday()]

        if day_name not in location.schedule:
            continue

        sched = location.schedule[day_name]
        open_h, open_m = map(int, sched.open.split(":"))
        close_h, close_m = map(int, sched.close.split(":"))
        slot_min = sched.slot_duration_minutes

        current = datetime(target_date.year, target_date.month, target_date.day, open_h, open_m)
        end = datetime(target_date.year, target_date.month, target_date.day, close_h, close_m)

        # Skip lunch break window
        break_start = break_end = None
        if sched.break_start and sched.break_end:
            bsh, bsm = map(int, sched.break_start.split(":"))
            beh, bem = map(int, sched.break_end.split(":"))
            break_start = datetime(target_date.year, target_date.month, target_date.day, bsh, bsm)
            break_end = datetime(target_date.year, target_date.month, target_date.day, beh, bem)

        for doctor in doctors[:2]:  # show max 2 doctors per day
            slot_time = current
            slot_count = 0
            while slot_time < end and slot_count < 3:
                if break_start and break_end and break_start <= slot_time < break_end:
                    slot_time = break_end
                    continue

                slots.append({
                    "slot_id": str(uuid.uuid4())[:8],
                    "clinic_id": location.id,
                    "clinic_name": location.name,
                    "clinic_address": location.address,
                    "doctor_name": doctor.name,
                    "specialty": doctor.specialty,
                    "date": target_date.strftime("%d/%m/%Y"),
                    "date_iso": target_date.isoformat(),
                    "time": slot_time.strftime("%H:%M"),
                    "day_label": _day_label_es(day_name),
                })
                from datetime import timedelta as td
                slot_time += td(minutes=slot_min)
                slot_count += 1

        if len(slots) >= 6:
            break

    return slots[:6]


def _day_label_es(day: str) -> str:
    labels = {
        "monday": "Lunes", "tuesday": "Martes", "wednesday": "Miércoles",
        "thursday": "Jueves", "friday": "Viernes", "saturday": "Sábado", "sunday": "Domingo",
    }
    return labels.get(day, day.capitalize())


def _demo_config() -> ClinicConfig:
    from datetime import date, timedelta
    demo_schedule = {day: DaySchedule(open="08:00", close="19:00", break_start="13:00", break_end="14:00")
                     for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]}
    demo_schedule["saturday"] = DaySchedule(open="09:00", close="14:00")

    return ClinicConfig(
        name="Clínica Demo",
        type="general",
        tagline="Tu salud, nuestra prioridad",
        language="es",
        locations=[
            ClinicLocation(
                id="loc_01",
                name="Clínica Demo — Centro",
                address="Calle Salud 123, Centro",
                city="Ciudad de México",
                phone="+52 55 1234 5678",
                whatsapp="+52 55 1234 5678",
                latitude=19.4326,
                longitude=-99.1332,
                schedule=demo_schedule,
                doctors=[
                    Doctor(id="dr_01", name="Dra. Ana López", specialty="Medicina General"),
                    Doctor(id="dr_02", name="Dr. Carlos Ruiz", specialty="Dermatología"),
                ],
                specialties=["Medicina General", "Dermatología", "Nutrición"],
            )
        ],
        qualification_rules={
            "min_duration_days": 0,
            "excluded_conditions": ["emergencia cardiovascular", "accidente cerebrovascular"],
            "require_location": True,
        },
    )
