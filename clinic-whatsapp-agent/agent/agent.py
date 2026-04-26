"""
Core Claude-powered conversation agent.
Handles the full qualification and booking flow via a stage-based state machine.
"""
import os
from typing import Optional
import anthropic

from .models import ConversationSession, ConversationStage, UrgencyLevel, AppointmentSlot
from .clinic_config import ClinicConfig, ClinicLocation, get_available_slots, load_clinic_config
from .geolocation import find_nearest_clinics, reverse_geocode, parse_whatsapp_location
from .prompts import (
    SYSTEM_PROMPT, WELCOME_PROMPT, DETECT_TREATMENT_PROMPT, QUALIFY_PROBLEM_PROMPT,
    QUALIFY_DURATION_PROMPT, QUALIFY_PREVIOUS_PROMPT, QUALIFY_URGENCY_PROMPT,
    REQUEST_LOCATION_PROMPT, CLINIC_MATCH_PROMPT, SHOW_SCHEDULE_PROMPT,
    BOOKING_CONFIRM_PROMPT, DISQUALIFIED_PROMPT,
)

EMERGENCY_KEYWORDS = [
    "infarto", "paro", "no respira", "no puedo respirar", "desmay",
    "pérdida de consciencia", "derrame", "911", "urgencia extrema",
    "heart attack", "can't breathe", "unconscious",
]

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


class ClinicAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.config: ClinicConfig = load_clinic_config()

    def _system_prompt(self) -> str:
        specialties = ", ".join(
            {s for loc in self.config.locations for s in loc.specialties}
        ) or "Medicina General"
        exclusions = self.config.qualification_rules.get("excluded_conditions", [])
        exclusion_text = ", ".join(exclusions) if exclusions else "ninguna condición específica"
        return SYSTEM_PROMPT.format(
            clinic_name=self.config.name,
            clinic_type=self.config.type,
            specialties=specialties,
            exclusion_rules=exclusion_text,
        )

    def _is_emergency(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in EMERGENCY_KEYWORDS)

    def _call_claude(
        self,
        session: ConversationSession,
        stage_instruction: str,
        extra_context: str = "",
    ) -> str:
        """Call Claude with conversation history + current stage instruction."""
        messages = [{"role": m["role"], "content": m["content"]} for m in session.messages]

        # Inject stage guidance as a user turn if messages exist, else as first turn
        guidance = f"[INSTRUCCIÓN DE ETAPA — no mostrar al usuario]: {stage_instruction}"
        if extra_context:
            guidance += f"\n[CONTEXTO ADICIONAL]: {extra_context}"

        if messages:
            # Add a hidden assistant nudge via a system-level instruction appended inline
            messages.append({"role": "user", "content": guidance})
        else:
            messages = [{"role": "user", "content": guidance}]

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=self._system_prompt(),
            messages=messages,
        )
        return response.content[0].text.strip()

    def _extract_intent(self, session: ConversationSession, text: str) -> dict:
        """Use Claude to extract structured intent from user message."""
        extraction_prompt = f"""Analiza este mensaje de un paciente y extrae información estructurada en JSON.
Mensaje: "{text}"

Devuelve SOLO un JSON válido con estos campos (usa null si no hay información):
{{
  "name": "nombre del paciente si lo mencionó",
  "treatment_type": "tipo de tratamiento o área médica mencionada",
  "specialty": "especialidad médica más apropiada",
  "problem_description": "descripción breve del problema",
  "duration": "tiempo con el problema si lo mencionó",
  "previous_treatments": "tratamientos previos si los mencionó",
  "urgency": "low|medium|high|emergency",
  "is_emergency": true o false,
  "wants_appointment": true o false
}}"""

        try:
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": extraction_prompt}],
            )
            import json
            text_out = resp.content[0].text.strip()
            # Strip markdown code blocks if present
            if text_out.startswith("```"):
                text_out = text_out.split("```")[1]
                if text_out.startswith("json"):
                    text_out = text_out[4:]
            return json.loads(text_out)
        except Exception:
            return {}

    async def process_message(
        self,
        session: ConversationSession,
        incoming_text: str,
        latitude: Optional[str] = None,
        longitude: Optional[str] = None,
    ) -> str:
        """Main entry point: process an incoming message and advance the state machine."""

        # Emergency check — always-on regardless of stage
        if self._is_emergency(incoming_text):
            session.stage = ConversationStage.DISQUALIFIED
            session.patient.disqualification_reason = "emergency"
            session.add_message("user", incoming_text)
            reply = (
                f"⚠️ Lo que describes suena a una emergencia médica. "
                f"Por favor llama al *911* de inmediato o dirígete a urgencias. "
                f"Tu vida es lo más importante. Si después de eso deseas agendar una consulta de seguimiento, "
                f"con gusto te ayudamos en {self.config.name}."
            )
            session.add_message("assistant", reply)
            return reply

        session.add_message("user", incoming_text)
        intent = self._extract_intent(session, incoming_text)

        # Update patient profile from extracted intent
        p = session.patient
        p.phone = session.phone
        if intent.get("name") and not p.name:
            p.name = intent["name"]
        if intent.get("treatment_type") and not p.treatment_type:
            p.treatment_type = intent["treatment_type"]
        if intent.get("specialty") and not p.specialty_needed:
            p.specialty_needed = intent["specialty"]
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

        # --- STATE MACHINE ---
        reply = await self._advance_stage(session, incoming_text, intent, latitude, longitude)
        session.add_message("assistant", reply)
        return reply

    async def _advance_stage(
        self,
        session: ConversationSession,
        text: str,
        intent: dict,
        latitude: Optional[str],
        longitude: Optional[str],
    ) -> str:
        stage = session.stage
        p = session.patient
        cfg = self.config

        if stage == ConversationStage.WELCOME:
            reply = self._call_claude(
                session,
                WELCOME_PROMPT.format(clinic_name=cfg.name, clinic_tagline=cfg.tagline),
            )
            session.stage = ConversationStage.DETECT_TREATMENT
            return reply

        if stage == ConversationStage.DETECT_TREATMENT:
            if p.treatment_type or p.problem_description:
                session.stage = ConversationStage.QUALIFY_PROBLEM
                return await self._advance_stage(session, text, intent, latitude, longitude)
            reply = self._call_claude(session, DETECT_TREATMENT_PROMPT)
            return reply

        if stage == ConversationStage.QUALIFY_PROBLEM:
            if p.problem_description:
                session.stage = ConversationStage.QUALIFY_DURATION
                return await self._advance_stage(session, text, intent, latitude, longitude)
            reply = self._call_claude(
                session,
                QUALIFY_PROBLEM_PROMPT.format(treatment_type=p.treatment_type or "tu consulta"),
            )
            return reply

        if stage == ConversationStage.QUALIFY_DURATION:
            # Accept text as duration even if not extracted
            if not p.duration_of_problem:
                p.duration_of_problem = text[:100]
            session.stage = ConversationStage.QUALIFY_PREVIOUS
            reply = self._call_claude(
                session,
                QUALIFY_DURATION_PROMPT.format(problem_description=p.problem_description or "tu problema"),
            )
            return reply

        if stage == ConversationStage.QUALIFY_PREVIOUS:
            if not p.previous_treatments:
                p.previous_treatments = text[:200]
            session.stage = ConversationStage.QUALIFY_URGENCY
            reply = self._call_claude(
                session,
                QUALIFY_PREVIOUS_PROMPT.format(
                    problem_description=p.problem_description or "tu problema",
                    duration=p.duration_of_problem or "un tiempo",
                ),
            )
            return reply

        if stage == ConversationStage.QUALIFY_URGENCY:
            # Evaluate qualification
            is_qualified = self._evaluate_qualification(session, text)
            if not is_qualified:
                session.stage = ConversationStage.DISQUALIFIED
                reply = self._call_claude(
                    session,
                    DISQUALIFIED_PROMPT.format(reason=p.disqualification_reason or "tu caso requiere atención especializada"),
                )
                return reply

            p.qualifies = True
            session.stage = ConversationStage.REQUEST_LOCATION
            reply = self._call_claude(
                session,
                REQUEST_LOCATION_PROMPT.format(specialty=p.specialty_needed or "tu especialidad"),
            )
            return reply

        if stage == ConversationStage.REQUEST_LOCATION:
            # Handle location share or text city
            coords = parse_whatsapp_location(text, latitude, longitude)
            if coords:
                p.latitude, p.longitude = coords
                city = await reverse_geocode(p.latitude, p.longitude)
                if city:
                    p.city = city
            else:
                # Treat text as city name
                p.city = text.strip()[:100]

            session.stage = ConversationStage.CLINIC_MATCH
            return await self._advance_stage(session, text, intent, latitude, longitude)

        if stage == ConversationStage.CLINIC_MATCH:
            nearby = self._find_matching_clinics(session)
            if not nearby:
                reply = (
                    f"No encontramos sucursales de {cfg.name} cerca de tu ubicación en este momento. "
                    f"Por favor llámanos al {cfg.locations[0].phone if cfg.locations else 'nuestro número'} "
                    f"y con gusto te orientamos. 🙏"
                )
                return reply

            session.available_slots = []
            for loc, dist in nearby:
                specialty = p.specialty_needed or (loc.specialties[0] if loc.specialties else "Medicina General")
                slots = get_available_slots(loc, specialty)
                for s in slots:
                    s["distance_km"] = dist
                session.available_slots.extend(slots)

            clinic_list = "\n".join(
                [f"• *{loc.name}* — {loc.address} ({dist} km)" for loc, dist in nearby]
            )
            session.stage = ConversationStage.SHOW_SCHEDULE
            reply = self._call_claude(
                session,
                CLINIC_MATCH_PROMPT.format(num_clinics=len(nearby)),
                extra_context=f"Sucursales encontradas:\n{clinic_list}",
            )
            return reply

        if stage == ConversationStage.SHOW_SCHEDULE:
            # Format available slots for the patient
            if not session.available_slots:
                session.stage = ConversationStage.BOOKING_CONFIRM
                return "No encontramos horarios disponibles por el momento. Uno de nuestros asesores te contactará pronto. 🙏"

            slots_text = self._format_slots(session.available_slots)
            session.stage = ConversationStage.BOOKING_CONFIRM
            reply = self._call_claude(
                session,
                SHOW_SCHEDULE_PROMPT.format(clinic_name=cfg.name),
                extra_context=f"Horarios disponibles:\n{slots_text}\n\nPide al paciente que elija un número del 1 al {len(session.available_slots)}.",
            )
            return reply

        if stage == ConversationStage.BOOKING_CONFIRM:
            # Try to detect which slot was chosen
            chosen = self._detect_slot_choice(text, session.available_slots)
            if chosen:
                session.selected_slot = chosen
                session.stage = ConversationStage.COMPLETED
                reply = self._call_claude(
                    session,
                    BOOKING_CONFIRM_PROMPT.format(
                        date=chosen["date"],
                        time=chosen["time"],
                        doctor=chosen["doctor_name"],
                        clinic_name=chosen["clinic_name"],
                        clinic_address=chosen["clinic_address"],
                    ),
                )
                return reply
            # Not clear — ask again
            slots_text = self._format_slots(session.available_slots)
            reply = self._call_claude(
                session,
                f"El paciente no eligió claramente. Muéstrale de nuevo los horarios numerados y pídele que escriba el número.",
                extra_context=f"Horarios:\n{slots_text}",
            )
            return reply

        if stage == ConversationStage.COMPLETED:
            reply = self._call_claude(
                session,
                "La cita ya fue confirmada. Si el paciente tiene más preguntas, respóndelas brevemente. "
                "Recuérdale que puede contactarnos si necesita cancelar o reprogramar.",
            )
            return reply

        if stage == ConversationStage.DISQUALIFIED:
            reply = self._call_claude(
                session,
                "El caso ya fue evaluado como no apto. Responde de forma empática a cualquier pregunta adicional.",
            )
            return reply

        return "¿En qué más puedo ayudarte? 😊"

    def _evaluate_qualification(self, session: ConversationSession, urgency_text: str) -> bool:
        """Simple rule-based qualification check."""
        p = session.patient
        rules = self.config.qualification_rules
        excluded = rules.get("excluded_conditions", [])

        combined_text = " ".join(filter(None, [
            p.problem_description, p.treatment_type, urgency_text
        ])).lower()

        for condition in excluded:
            if condition.lower() in combined_text:
                p.disqualification_reason = f"el problema describe: {condition}"
                p.qualifies = False
                return False

        # Check available specialties
        all_specialties = [s.lower() for loc in self.config.locations for s in loc.specialties]
        if p.specialty_needed and all_specialties:
            specialty_lower = p.specialty_needed.lower()
            if not any(specialty_lower in s or s in specialty_lower for s in all_specialties):
                p.disqualification_reason = f"no ofrecemos {p.specialty_needed}"
                p.qualifies = False
                return False

        return True

    def _find_matching_clinics(self, session: ConversationSession) -> list[tuple[ClinicLocation, float]]:
        p = session.patient
        if p.latitude and p.longitude:
            return find_nearest_clinics(p.latitude, p.longitude, self.config.locations)
        # Fallback: return all locations without distance
        return [(loc, 0.0) for loc in self.config.locations[:3]]

    def _format_slots(self, slots: list[dict]) -> str:
        lines = []
        for i, s in enumerate(slots, 1):
            dist = f" ({s.get('distance_km', 0):.1f} km)" if s.get("distance_km") else ""
            lines.append(
                f"{i}. {s['day_label']} {s['date']} a las {s['time']} "
                f"con {s['doctor_name']}{dist}"
            )
        return "\n".join(lines)

    def _detect_slot_choice(self, text: str, slots: list[dict]) -> Optional[dict]:
        """Detect if the user chose a slot by number (1-9)."""
        import re
        text_clean = text.strip()
        match = re.search(r"\b([1-9])\b", text_clean)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(slots):
                return slots[idx]
        # Check if text matches a time or date
        for s in slots:
            if s["time"] in text or s["date"] in text:
                return s
        return None
