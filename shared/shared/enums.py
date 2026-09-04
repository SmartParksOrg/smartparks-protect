"""Enumerations stored as text columns with a check constraint (see `shared.models.base`).

Text plus a check is used instead of PostgreSQL enum types because adding a value to a native enum
cannot run inside a transaction and complicates migrations.
"""

from enum import StrEnum


class Role(StrEnum):
    """Project roles. Server admin is `User.is_superuser`, not a membership row."""

    PROJECT_VIEWER = "project-viewer"
    PROJECT_ADMIN = "project-admin"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    MCP = "mcp"


class OAuthClientKind(StrEnum):
    """How an AI client was registered (architecture 27.5)."""

    DYNAMIC = "dynamic"  # RFC 7591 dynamic client registration
    METADATA_DOCUMENT = "metadata_document"  # client id metadata document at the client id URL


class EntityGroup(StrEnum):
    TRACKED = "tracked"
    INFRASTRUCTURE = "infrastructure"
    ENVIRONMENTAL = "environmental"
    EQUIPMENT = "equipment"
    SITE = "site"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class FeatureType(StrEnum):
    SITE = "site"
    ZONE = "zone"
    GEOFENCE = "geofence"
    ROUTE = "route"


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    INVENTORY = "inventory"
    REPAIR = "repair"
    RETIRED = "retired"


class ValueType(StrEnum):
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    TEXT = "text"
    JSON = "json"


class ProcessingStatus(StrEnum):
    """Status of a SourceEvent."""

    RECEIVED = "received"
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    UNASSIGNED = "unassigned"
    IGNORED = "ignored"


class AcquisitionChannel(StrEnum):
    """Route from the device to the upstream system (architecture 25.1)."""

    LORAWAN = "lorawan"
    WEBBLE = "webble"
    LOG_FILE = "log_file"
    IRIDIUM = "iridium"
    CELLULAR = "cellular"
    API = "api"
    OTHER = "other"


class IngestionMethod(StrEnum):
    """How Smart Parks Protect received the delivery (architecture 25.1)."""

    MQTT = "mqtt"
    WEBHOOK = "webhook"
    POLLING = "polling"
    WEBSOCKET = "websocket"
    BROWSER_SYNC = "browser_sync"
    FILE_UPLOAD = "file_upload"


class ConnectivityStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class TraceStatus(StrEnum):
    """Status of a ProcessingTrace and of a ProcessingStep (architecture 26.1)."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    SKIPPED = "skipped"
    DUPLICATE = "duplicate"
    RETRYING = "retrying"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class TraceClass(StrEnum):
    """Retention class of a trace (architecture 26.9)."""

    ROUTINE = "routine"
    FAILED = "failed"
    COMMAND = "command"
    AUDIT = "audit"


class ErrorCode(StrEnum):
    """Stable application error codes (architecture 26.5)."""

    CONNECTIVITY_AUTH_FAILED = "CONNECTIVITY_AUTH_FAILED"
    CONNECTIVITY_UNAVAILABLE = "CONNECTIVITY_UNAVAILABLE"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_IDENTITY_AMBIGUOUS = "DEVICE_IDENTITY_AMBIGUOUS"
    PROJECT_NOT_ASSIGNED = "PROJECT_NOT_ASSIGNED"
    PAYLOAD_DECODE_FAILED = "PAYLOAD_DECODE_FAILED"
    TIMESTAMP_INVALID = "TIMESTAMP_INVALID"
    CANONICALIZATION_FAILED = "CANONICALIZATION_FAILED"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    RULE_EVALUATION_FAILED = "RULE_EVALUATION_FAILED"
    ACTION_FAILED = "ACTION_FAILED"
    INTEGRATION_DELIVERY_FAILED = "INTEGRATION_DELIVERY_FAILED"
    COMMAND_REJECTED = "COMMAND_REJECTED"
    COMMAND_EXPIRED = "COMMAND_EXPIRED"
    FILE_PARSE_FAILED = "FILE_PARSE_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ExportFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"
    GEOJSON = "geojson"
    GPX = "gpx"


class ExportDataset(StrEnum):
    """What an export contains (architecture 14, data level)."""

    SOURCE_EVENTS = "source_events"  # raw: inbound messages with their payload
    POSITIONS = "positions"  # normalized
    MEASUREMENTS = "measurements"  # normalized
    AGGREGATES = "aggregates"  # bucketed series, same query as the Data Explorer


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class ActionType(StrEnum):
    """What an automation does with an event (architecture 16). Integration and command are
    reserved for phases 8 and 6; the automation service rejects them until then."""

    NOTIFY = "notify"
    WEBHOOK = "webhook"
    INTEGRATION = "integration"
    COMMAND = "command"


class CommandStatus(StrEnum):
    """Command lifecycle (architecture 17.4). A stage the provider cannot observe stays
    unreached, it is never fabricated."""

    CREATED = "created"
    ENCODED = "encoded"
    SUBMITTED = "submitted"
    ACCEPTED_BY_NETWORK = "accepted_by_network"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    TRANSMITTED = "transmitted"
    ACKNOWLEDGED = "acknowledged"
    CONFIRMED_BY_DEVICE = "confirmed_by_device"
    FAILED = "failed"
    EXPIRED = "expired"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class IntegrationObjectType(StrEnum):
    """What an outbound integration forwards (architecture 18)."""

    POSITION = "position"
    EVENT = "event"
    MEASUREMENT = "measurement"


class DeliveryOrigin(StrEnum):
    """How an integration delivery row came to exist."""

    LIVE = "live"
    BACKFILL = "backfill"
    RETRY = "retry"
    TEST = "test"


class BackfillStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
