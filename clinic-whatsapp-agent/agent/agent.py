"""
Motor del agente — personalidad de médico experto, flujo corto (4 pasos).
"""
import json
import os
from pathlib import Path
from typing import Optional
import anthropic

from .models import ConversationSession, ConversationStage, UrgencyLevel
from .clinic_config import ClinicConfig, ClinicLocation, get_available_slots, load_clinic_config
from .geolocation import (
    find_nearest_clinics, reverse_geocode, parse_whatsapp_location,
    geocode_address, get_directions_link,
)
from .prompts import (
    SYSTEM_PROMPT, WELCOME_PROMPT, DETECT_AND_EDUCATE_PROMPT,
    QUALIFY_AND_PUSH_PROMPT, REQUEST_LOCATION_PROMPT,
    SHOW_SLOTS_PROMPT, BOOKING_CONFIRM_PROMPT, DISQUALIFIED_PROMPT,
)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

EMERGENCY_KEYWORDS = [
    "infarto", "paro", "no respiro", "no puedo respirar", "dificultad respirar",
    "perdida de consciencia", "inconsciente", "ictus", "derrame cerebral",
    "convulsion", "hemorragia grave", "sangrado abundante",
]

_TREATMENTS_PATH = Path(__file__).parent.parent / "config" / "treatments.json"
_treatments_cache: Optional[dict] = None


def _load_treatments() -> dict:
    global _treatments_cache
    if _treatments_cache:
        return _treatments_cache
    if _TREATMENTS_PATH.exists():
        with open(_TREATMENTS_PATH) as f:
            _treatments_cache = json.load(f).get("specialties", {})
    else:
        _treatments_cache = {}
    return _treatments_cache


def _match_specialty(text: str, treatments: dict) -> Optional[tuple[str, dict]]:
    """Find the best matching specialty from the text."""
    lower = text.lower()
    best_match = None
    best_score = 0
    for key, spec in treatments.items():
        keywords = spec.get("keywords", [])
        score = sum(1 for kw in keywords if kw in lower)
        if score > best_score:
            best_score = score
            best_match = (key, spec)
    return best_match if best_score > 0 else None


def _treatment_context(specialty_key: Optional[str], treatments: dict) -> str:
    if not specialty_key or specialty_key not in treatments:
        return "Clínica general con múltiples especialidades."
    spec = treatments[specialty_key]
    items = []
    for t in list(spec.get("treatments", {}).values())[:3]:
        items.append(f"- {t['name']}: {t['description']} Resultado: {t['resultado']}")
    urgency = spec.get("urgency_push", "")
    return "\n".join(items) + (f"\n\nARGUMENTO CLAVE: {urgency}" if urgency else "")


class ClinicAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.config: ClinicConfig = load_clinic_config()
        self.treatments = _load_treatments()

    def _system_prompt(self, specialty_key: Optional[str] = None) -> str:
        specialties = ", ".join({s for loc in self.config.locations for s in loc.specialties})
        exclusions = self.config.qualification_rules.get("excluded_conditions", [])
        treatment_ctx = _treatment_context(specialty_key, self.treatments)
        return SYSTEM_PROMPT.format(
            clinic_name=self.config.name,
            clinic_type=self.config.type,
            specialties=specialties or "Medicina General",
            treatment_context=treatment_ctx,
            exclusion_rules=", ".join(exclusions) if exclusions else "ninguna",
        )

    def _is_emergency(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in EMERGENCY_KEYWORDS)

    def _call_claude(self, session: ConversationSession, instruction: str, context: str = "") -> str:
        messages = [{"role": m["role"], "content": m["content"]} for m in session.messages]
        prompt = f"[INSTRUCCIÓN INTERNA]: {instruction}"
        if context:
            prompt += f"\n[DATOS]: {context}"
        messages.append({"role": "user", "content": prompt})
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=self._system_prompt(session.patient.specialty_key),
            messages=messages,
        )
        return response.content[0].text.strip()

    def _extract_intent(self, text: str) -> dict:
        prompt = f"""Analiza este mensaje de un paciente y extrae en JSON (null si no hay info):
Mensaje: "{text}"
{{
  "name": "nombre si lo mencionó",
  "specialty_hint": "área médica: capilar|estetica|odontologia|fisioterapia|dermatologia|nutricion|psicologia|medicina_general|null",
  "problem_description": "descripción del problema en ≤15 palabras",
  "duration": "tiempo con el problema",
  "previous_treatments": "tratamientos o médicos previos",
  "urgency": "low|medium|high|emergency",
  "location_text": "ciudad, barrio o código postal mencionado"
}}
Devuelve SOLO el JSON."""
        try:
            resp = self.client.messages.create(
                model=MODEL, max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            return json.loads(raw)
        except Exception:
            return {}

    async def process_message(
        self,
        session: ConversationSession,
        text: str,
        latitude: Optional[str] = None,
        longitude: Optional[str] = None,
    ) -> str:
        if self._is_emergency(text):
            session.stage = ConversationStage.DISQUALIFIED
            session.patient.disqualification_reason = "emergency"
            session.add_message("user", text)
            reply = "Lo que describes puede ser una emergencia médica. Llama al *112* ahora o acude a Urgencias inmediatamente. Tu vida es lo primero."
            session.add_message("assistant", reply)
            return reply

        session.add_message("user", text)
        intent = self._extract_intent(text)
        p = session.patient
        p.phone = session.phone

        if intent.get("name") and not p.name:
            p.name = intent["name"]
        if intent.get("problem_description") and not p.problem_description:
            p.problem_description = intent["problem_description"]
        if intent.get("duration") and not p.duration_of_problem:
            p.duration_of_problem = intent["duration"]
        if intent.get("previous_treatments") and not p.previous_treatments:
            p.previous_treatments = intent["previous_treatments"]
        if intent.get("urgency"):
            try:
                p.urgency = UrgencyLevel(intent["urgency"])
            except ValueError:
                pass

        # Match specialty
        if not hasattr(p, "specialty_key"):
            p.specialty_key = None
        hint = intent.get("specialty_hint") or ""
        if hint and hint != "null" and not p.specialty_key:
            p.specialty_key = hint
            if hint in self.treatments:
                spec = self.treatments[hint]
                p.specialty_needed = spec.get("label", hint)
                if not p.treatment_type:
                    p.treatment_type = spec.get("label", hint)
        elif not p.specialty_key and p.problem_description:
            match = _match_specialty(p.problem_description + " " + text, self.treatments)
            if match:
                p.specialty_key = match[0]
                p.specialty_needed = match[1].get("label", match[0])

        reply = await self._advance(session, text, intent, latitude, longitude)
        session.add_message("assistant", reply)
        return reply

    async def _advance(self, session, text, intent, latitude, longitude) -> str:
        stage = session.stage
        p = session.patient
        cfg = self.config

        # ── WELCOME ──────────────────────────────────────────────────────────
        if stage == ConversationStage.WELCOME:
            reply = self._call_claude(session, WELCOME_PROMPT.format(
                clinic_name=cfg.name, clinic_tagline=cfg.tagline))
            session.stage = ConversationStage.DETECT_TREATMENT
            return reply

        # ── DETECT TREATMENT + EDUCATE ────────────────────────────────────
        if stage == ConversationStage.DETECT_TREATMENT:
            if not p.problem_description:
                return self._call_claude(session, "Pregunta al paciente qué problema o molestia le trae. Una línea, directo.")

            spec_data = self.treatments.get(p.specialty_key or "", {})
            treatment_info = _treatment_context(p.specialty_key, self.treatments)

            reply = self._call_claude(session,
                DETECT_AND_EDUCATE_PROMPT.format(
                    problem=p.problem_description,
                    treatment_info=treatment_info,
                ))
            session.stage = ConversationStage.QUALIFY_PROBLEM
            return reply

        # ── QUALIFY (1 question only) ─────────────────────────────────────
        if stage == ConversationStage.QUALIFY_PROBLEM:
            if not p.duration_of_problem:
                p.duration_of_problem = text[:100]
            if not p.previous_treatments:
                p.previous_treatments = text[:150]

            # Evaluate and push to consultation immediately
            if not self._evaluate_qualification(session, text):
                session.stage = ConversationStage.DISQUALIFIED
                return self._call_claude(session, DISQUALIFIED_PROMPT.format(
                    reason=p.disqualification_reason or "fuera de nuestras especialidades"))

            p.qualifies = True
            session.stage = ConversationStage.REQUEST_LOCATION

            reply = self._call_claude(session,
                QUALIFY_AND_PUSH_PROMPT.format(
                    problem=p.problem_description or "tu consulta",
                    duration=p.duration_of_problem or "no especificada",
                    previous=p.previous_treatments or "ninguno",
                ))
            return reply

        # ── LOCATION ─────────────────────────────────────────────────────
        if stage == ConversationStage.REQUEST_LOCATION:
            # Check if this message has location or city
            coords = parse_whatsapp_location(text, latitude, longitude)
            if coords:
                p.latitude, p.longitude = coords
            else:
                loc_text = intent.get("location_text") or text.strip()
                if loc_text and len(loc_text) > 2:
                    coords = await geocode_address(loc_text + ", España")
                    if coords:
                        p.latitude, p.longitude = coords
                        p.city = loc_text

            if p.latitude and p.longitude and not p.city:
                p.city = await reverse_geocode(p.latitude, p.longitude)

            session.stage = ConversationStage.CLINIC_MATCH
            return await self._advance(session, text, intent, latitude, longitude)

        # ── CLINIC MATCH ──────────────────────────────────────────────────
        if stage == ConversationStage.CLINIC_MATCH:
            # If still no location, ask for it
            if not p.latitude and not p.city:
                return self._call_claude(session, REQUEST_LOCATION_PROMPT.format(
                    specialty=p.specialty_needed or "tu especialidad"))

            nearby = self._find_clinics(session)
            if not nearby:
                return (f"Por el momento no tenemos un centro cerca de tu zona. "
                        f"Llámanos al {cfg.locations[0].phone} y buscamos la mejor solución para ti.")

            session.available_slots = []
            for loc, dist in nearby:
                specialty = p.specialty_needed or (loc.specialties[0] if loc.specialties else "Medicina General")
                slots = get_available_slots(loc, specialty)
                for s in slots:
                    s["distance_km"] = dist
                    s["maps_link"] = get_directions_link(loc.latitude, loc.longitude)
                session.available_slots.extend(slots)

            session.stage = ConversationStage.SHOW_SCHEDULE

            # Pick the closest clinic's doctor specialty
            best_loc = nearby[0][0]
            doctor_specialty = p.specialty_needed or (best_loc.specialties[0] if best_loc.specialties else "tu especialidad")

            slots_text = self._format_slots(session.available_slots[:6])
            return self._call_claude(session,
                SHOW_SLOTS_PROMPT.format(
                    clinic_name=best_loc.name,
                    doctor_specialty=doctor_specialty,
                ),
                context=f"Huecos disponibles:\n{slots_text}")

        # ── SHOW SCHEDULE (already shown, waiting for choice) ─────────────
        if stage == ConversationStage.SHOW_SCHEDULE:
            chosen = self._detect_choice(text, session.available_slots)
            if chosen:
                session.selected_slot = chosen
                session.stage = ConversationStage.BOOKING_CONFIRM
                loc = next((l for l in cfg.locations if l.id == chosen["clinic_id"]), None)
                maps = get_directions_link(loc.latitude, loc.longitude) if loc else ""
                return self._call_claude(session,
                    BOOKING_CONFIRM_PROMPT.format(
                        date=chosen["date"], day=chosen.get("day_label", ""),
                        time=chosen["time"], doctor=chosen["doctor_name"],
                        specialty=chosen["specialty"],
                        clinic_name=chosen["clinic_name"],
                        clinic_address=chosen["clinic_address"],
                        maps_link=maps,
                    ))
            # Repeat slots
            slots_text = self._format_slots(session.available_slots[:6])
            return self._call_claude(session,
                "El paciente no eligió claramente. Muéstrale los huecos numerados de nuevo y pide que responda con el número.",
                context=slots_text)

        # ── BOOKING CONFIRM ───────────────────────────────────────────────
        if stage == ConversationStage.BOOKING_CONFIRM:
            return self._call_claude(session,
                "Cita ya confirmada. Responde cualquier duda brevemente y recuerda que puede cancelar escribiéndonos.")

        # ── COMPLETED ────────────────────────────────────────────────────
        if stage == ConversationStage.COMPLETED:
            return self._call_claude(session, "La cita está confirmada. Responde dudas con brevedad médica.")

        # ── DISQUALIFIED ──────────────────────────────────────────────────
        if stage == ConversationStage.DISQUALIFIED:
            return self._call_claude(session, "Caso ya evaluado. Responde con empatía.")

        return "¿En qué más puedo ayudarte?"

    def _evaluate_qualification(self, session, text: str) -> bool:
        p = session.patient
        excluded = self.config.qualification_rules.get("excluded_conditions", [])
        combined = " ".join(filter(None, [p.problem_description, p.treatment_type, text])).lower()
        for cond in excluded:
            if cond.lower() in combined:
                p.disqualification_reason = f"describe síntomas de: {cond}"
                p.qualifies = False
                return False
        # Check red_flags from specialty
        if p.specialty_key and p.specialty_key in self.treatments:
            red_flags = self.treatments[p.specialty_key].get("red_flags", [])
            for flag in red_flags:
                if flag.lower() in combined:
                    p.disqualification_reason = f"señal de alarma detectada: {flag}"
                    p.qualifies = False
                    return False
        return True

    def _find_clinics(self, session) -> list[tuple[ClinicLocation, float]]:
        p = session.patient
        if p.latitude and p.longitude:
            return find_nearest_clinics(p.latitude, p.longitude, self.config.locations)
        return [(loc, 0.0) for loc in self.config.locations[:3]]

    def _format_slots(self, slots: list[dict]) -> str:
        lines = []
        for i, s in enumerate(slots, 1):
            dist = f" · {s['distance_km']:.1f} km" if s.get("distance_km") else ""
            lines.append(f"{i}. {s['day_label']} {s['date']} — {s['time']} — {s['doctor_name']}{dist}")
        return "\n".join(lines)

    def _detect_choice(self, text: str, slots: list[dict]) -> Optional[dict]:
        import re
        m = re.search(r"\b([1-9])\b", text.strip())
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(slots):
                return slots[idx]
        for s in slots:
            if s["time"] in text or s["date"] in text:
                return s
        return None
