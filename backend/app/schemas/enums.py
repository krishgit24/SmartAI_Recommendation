from enum import Enum


class Recommendation(str, Enum):
    RETRY_NOW = "RETRY_NOW"
    RETRY_LATER = "RETRY_LATER"
    RETRY_AFTER_UPDATE = "RETRY_AFTER_UPDATE"
    DONT_RETRY = "DONT_RETRY"
    NO_RECOMMENDATION = "NO_RECOMMENDATION"


class PaymentRail(str, Enum):
    RTGS = "RTGS"
    NEFT = "NEFT"
    SEPA = "SEPA"
    SWIFT = "SWIFT"
    FASTER_PAYMENTS = "Faster Payments"
    ACH = "ACH"
