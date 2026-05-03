from .enums import ReasonForCalling, SmsCategory

# Mapping reason -> SMS esperado(s). Si la llamada terminó OK y no se envió
# uno de estos cuando correspondía, es WRONG_SMS.
SMS_EXPECTED_MAP: dict[ReasonForCalling, list[SmsCategory]] = {
    ReasonForCalling.RESERVATION: [SmsCategory.RESERVATION],
    ReasonForCalling.MENU_DIETARY: [SmsCategory.MENU],
    ReasonForCalling.TAKEOUT_DELIVERY: [SmsCategory.DELIVERY, SmsCategory.PICKUP],
    ReasonForCalling.GENERAL_INFO: [SmsCategory.DIRECTIONS, SmsCategory.WEB],
    ReasonForCalling.EVENTS_HOLIDAYS: [SmsCategory.EXPERIENCES, SmsCategory.LARGE_PARTY_FORM],
    ReasonForCalling.PRIVATE_EVENT: [SmsCategory.PRIVATE_EVENTS],
    ReasonForCalling.CATERING: [SmsCategory.CATERING],
    ReasonForCalling.GIFT_CARD: [SmsCategory.GIFTCARDS],
    ReasonForCalling.EMPLOYMENT: [SmsCategory.JOB_FORM, SmsCategory.CAREERS_WEB],
}

# Restaurantes válidos en el dataset
KNOWN_RESTAURANTS = ["BG Las Olas", "BG Doral", "BG Brickell"]

# Threshold para considerar transfer "muy rápido" (potencial bypass)
BYPASS_DURATION_THRESHOLD_SECONDS = 25

# Threshold para spam
SPAM_DURATION_THRESHOLD_SECONDS = 60

# Generador
GENERATOR_DEFAULT_BATCH_SIZE = 5
GENERATOR_DEFAULT_MIN_DELAY = 0.5
GENERATOR_DEFAULT_MAX_DELAY = 3.0

# Métricas — ventanas
WINDOW_SHORT = 50    # últimas 50 llamadas
WINDOW_LONG = 100    # últimas 100 llamadas (para WRONG_INFO, LOOP)
WINDOW_PER_RESTAURANT = 20

# Métricas — umbrales (ver módulo 3)
THRESHOLDS = {
    "resolution_rate_warning": 0.60,           # < 60%
    "error_rate_warning": 0.15,                # > 15%
    "error_rate_critical": 0.25,               # > 25%
    "human_review_rate_warning": 0.20,         # > 20%
    "high_priority_review_rate_critical": 0.10,
    "wrong_transfer_rate_warning": 0.08,
    "wrong_info_rate_critical": 0.03,
    "loop_rate_critical": 0.05,
    "restaurant_delta_warning": 0.15,          # 15pp diff entre locales
}
