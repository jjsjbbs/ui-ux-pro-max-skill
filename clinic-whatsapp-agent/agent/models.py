from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ConversationStage(str, Enum):
    WELCOME = "welcome"
    DETECT_TREATMENT = "detect_treatment"
    QUALIFY_PROBLEM = "qualify_problem"
    QUALIFY_DURATION = "qualify_duration"
    QUALIFY_PREVIOUS = "qualify_previous"
    QUALIFY_URGENCY = "qualify_urgency"
    REQUEST_LOCATION = "request_location"
    CLINIC_MATCH = "clinic_match"
    SHOW_SCHEDULE = "show_schedule"
    BOOKING_CONFIRM = "booking_confirm"
    COMPLETED = "completed"
    DISQUALIFIED = "disqualified"


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EMERGENCY = "emergency"


@dataclass
class PatientProfile:
    phone: str
    name: Optional[str] = None
    problem_description: Optional[str] = None
    treatment_type: Optional[str] = None
    specialty_needed: Optional[str] = None
    duration_of_problem: Optional[str] = None
    previous_treatments: Optional[str] = None
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    qualifies: Optional[bool] = None
    disqualification_reason: Optional[str] = None


@dataclass
class AppointmentSlot:
    clinic_id: str
    clinic_name: str
    clinic_address: str
    doctor_name: str
    specialty: str
    date: str
    time: str
    slot_id: str
    distance_km: Optional[float] = None


@dataclass
class ConversationSession:
    phone: str
    stage: ConversationStage = ConversationStage.WELCOME
    patient: PatientProfile = field(default_factory=lambda: PatientProfile(phone=""))
    messages: list = field(default_factory=list)
    available_slots: list = field(default_factory=list)
    selected_slot: Optional[AppointmentSlot] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    language: str = "es"

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "phone": self.phone,
            "stage": self.stage.value,
            "patient": {
                "name": self.patient.name,
                "problem": self.patient.problem_description,
                "treatment_type": self.patient.treatment_type,
                "specialty": self.patient.specialty_needed,
                "duration": self.patient.duration_of_problem,
                "previous_treatments": self.patient.previous_treatments,
                "urgency": self.patient.urgency.value,
                "city": self.patient.city,
                "qualifies": self.patient.qualifies,
            },
            "messages_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "language": self.language,
        }
