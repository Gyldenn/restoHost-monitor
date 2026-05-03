from enum import Enum

# ─────────── Reasons (valores EXACTOS de producción) ───────────

class ReasonForCalling(str, Enum):
    RESERVATION = "Making a Reservation or Inquiring About Reservations"
    HOURS_WAIT = "Questions about restaurant hours and wait times"
    GENERAL_INFO = "General information and amenities"
    EVENTS_HOLIDAYS = "Special event or holiday inquiry"
    TAKEOUT_DELIVERY = "Placing an order for takeout or delivery"
    MENU_DIETARY = "Menu inquiries and special dietary needs"
    LOST_ITEMS = "Lost items inquiries"
    EMPLOYMENT = "Employment opportunities or business inquiries"
    TECHNICAL = "Assistance with online platforms and technical issues"
    PRIVATE_EVENT = "Private event or client custom event inquiry"
    CATERING = "Catering request"
    GIFT_CARD = "Gift card request"
    PAYMENT = "Payment issues"
    MANAGER_REQUEST = (
        "Request to speak to a human, to a person, to customer service, "
        "to the host or the hostess"
    )
    MANAGER_REQUEST_ALT = (
        "Request to speak to a human, to a person, to customer support, "
        "to the representative or to someone"
    )

# Para visualización (display label)
REASON_LABELS = {
    ReasonForCalling.RESERVATION: "Reservations",
    ReasonForCalling.HOURS_WAIT: "Hours & Wait Times",
    ReasonForCalling.GENERAL_INFO: "General Info",
    ReasonForCalling.EVENTS_HOLIDAYS: "Events / Holidays",
    ReasonForCalling.TAKEOUT_DELIVERY: "Takeout / Delivery",
    ReasonForCalling.MENU_DIETARY: "Menu / Dietary",
    ReasonForCalling.LOST_ITEMS: "Lost Items",
    ReasonForCalling.EMPLOYMENT: "Employment / Business",
    ReasonForCalling.TECHNICAL: "Technical Issues",
    ReasonForCalling.PRIVATE_EVENT: "Private Event",
    ReasonForCalling.CATERING: "Catering",
    ReasonForCalling.GIFT_CARD: "Gift Card",
    ReasonForCalling.PAYMENT: "Payment Issues",
    ReasonForCalling.MANAGER_REQUEST: "Manager Request",
    ReasonForCalling.MANAGER_REQUEST_ALT: "Manager Request (alt)",
}

MANAGER_REQUEST_REASONS = {
    ReasonForCalling.MANAGER_REQUEST,
    ReasonForCalling.MANAGER_REQUEST_ALT,
}

# ─────────── Call end reason ───────────

class CallEndReason(str, Enum):
    AGENT_HANGUP = "AgentHangup"
    USER_HANGUP = "UserHangup"
    USER_INACTIVITY = "UserInactivity"
    CALL_TRANSFER = "CallTransfer"

# ─────────── SMS categories ───────────

class SmsCategory(str, Enum):
    RESERVATION = "reservation"
    CSF = "csf"
    MENU = "menu"
    DIRECTIONS = "directions"
    DELIVERY = "delivery"
    LARGE_PARTY_FORM = "large party form"
    EXPERIENCES = "experiences"
    WAITLIST = "waitlist"
    PRIVATE_EVENTS = "private events"
    CATERING = "catering"
    GIFTCARDS = "giftcards"
    JOB_FORM = "job form"
    CAREERS_WEB = "careers web"
    SOCIAL_MEDIA = "social media"
    WEB = "web"
    PICKUP = "pickup"

# ─────────── Yes/No (los campos del JSON usan strings) ───────────

class YesNo(str, Enum):
    YES = "yes"
    NO = "no"

# ─────────── Output del clasificador ───────────

class ErrorType(str, Enum):
    NO_ERROR = "NO_ERROR"
    WRONG_SMS = "WRONG_SMS"
    WRONG_TRANSFER = "WRONG_TRANSFER"
    WRONG_INFO = "WRONG_INFO"
    LOOP = "LOOP"
    INCOMPLETE = "INCOMPLETE"
    AMBIGUOUS = "AMBIGUOUS"

class OutcomeCategory(str, Enum):
    RESOLVED = "Resolved"
    TRANSFERRED = "Transferred"
    SPAM = "Spam"
    ERROR = "Error"
    AMBIGUOUS = "Ambiguous"

class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class AlertSeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
