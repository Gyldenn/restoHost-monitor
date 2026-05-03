from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    AlertSeverity, CallEndReason, ErrorType, OutcomeCategory,
    Priority, ReasonForCalling, YesNo,
)

# ─────────────────────────────────────────────────────────
# CallRecord — schema EXACTO del JSON de producción
# ─────────────────────────────────────────────────────────

class CallRecord(BaseModel):
    """Schema 1:1 con el JSON del apéndice. NO renombrar campos: respetamos
    camelCase y los strings exactos. extra='allow' porque algunos campos
    opcionales (mentionedMenuItems, reasonForEvent) aparecen condicionalmente.
    """
    model_config = ConfigDict(extra="allow")

    conversationId: str
    restaurantName: str
    callStartTime: str   # ISO 8601 con offset, p.ej. "2026-04-01T19:32:10.000-04:00"
    callDuration: str    # formato "MM:SS"
    callEndReason: CallEndReason
    callWithinOfficeHours: bool
    reasonForCalling: str    # libre porque puede ser "" o NULL → unclassified
    reasonForTransfering: str = ""
    reasonForSendingText: str = ""    # CSV de SmsCategory; libre porque LLM puede dar texto libre
    numberOfTextsSent: int = 0
    partySize: str = ""
    partysizenumber: str = ""
    detectederror: str = "No Error Detected"
    errorCategory: str = "No Error Detected"
    customerfrustration: YesNo = YesNo.NO
    speakInSpanish: YesNo = YesNo.NO
    menuMention: YesNo = YesNo.NO
    eventMention: YesNo = YesNo.NO
    callsHighlights: str = "No Highlight"
    friendlysummary: str
    conversation: str

    # Helpers convenientes (no son campos del JSON)
    def duration_seconds(self) -> int:
        try:
            mm, ss = self.callDuration.split(":")
            return int(mm) * 60 + int(ss)
        except Exception:
            return 0

    def sms_categories(self) -> list[str]:
        if not self.reasonForSendingText:
            return []
        return [s.strip().lower() for s in self.reasonForSendingText.split(",") if s.strip()]

    def reason_enum(self) -> ReasonForCalling | None:
        try:
            return ReasonForCalling(self.reasonForCalling)
        except ValueError:
            return None

# ─────────────────────────────────────────────────────────
# Classification — output del Módulo 2
# ─────────────────────────────────────────────────────────

class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversationId: str
    outcome_category: OutcomeCategory
    error_type: ErrorType
    error_description: str = Field(..., max_length=500)
    expected_behavior: str = Field(..., max_length=500)
    human_review_required: bool
    human_review_reason: str = Field(default="", max_length=300)
    human_review_priority: Priority | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    rules_triggered: list[str] = Field(default_factory=list)
    classified_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("human_review_priority")
    @classmethod
    def priority_only_if_required(cls, v, info):
        # Si human_review_required=True, priority NO puede ser None.
        # Si False, priority debe ser None.
        # Validación cruzada se hace en model_validator si fuera necesario.
        return v

# ─────────────────────────────────────────────────────────
# Alert — output del Módulo 3
# ─────────────────────────────────────────────────────────

class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: str
    severity: AlertSeverity
    metric: str                          # nombre de la métrica
    current_value: float
    threshold: float
    restaurant: str | None = None
    timestamp: datetime
    top_contributing_calls: list[str] = Field(default_factory=list, max_length=5)
    recommended_action: str = Field(..., max_length=400)

# ─────────────────────────────────────────────────────────
# MetricsSnapshot — estado actual del sistema
# ─────────────────────────────────────────────────────────

class MetricsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    total_calls: int
    resolution_rate: float | None
    error_rate: float | None
    human_review_rate: float | None
    high_priority_review_rate: float | None
    wrong_transfer_rate: float | None
    wrong_info_rate: float | None
    loop_rate: float | None
    error_rate_by_restaurant: dict[str, float] = Field(default_factory=dict)
    score_trend_7d: float | None = None
    custom_metric_value: float | None = None     # módulo 3 elige nombre
    custom_metric_name: str | None = None
    outcome_distribution: dict[str, int] = Field(default_factory=dict)
    error_type_distribution: dict[str, int] = Field(default_factory=dict)

# ─────────────────────────────────────────────────────────
# ReviewState — estado mutable de revisión humana (Módulo 4)
# ─────────────────────────────────────────────────────────

class ReviewState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed: dict[str, datetime] = Field(default_factory=dict)
    # key = conversationId, value = timestamp en que se marcó como revisada
