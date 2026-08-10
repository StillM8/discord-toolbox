"""Neutral application vocabulary shared across the modular monolith."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


def _empty_string_map() -> dict[str, str]:
    return {}


def _empty_object_map() -> dict[str, object]:
    return {}


class CapabilityName(StrEnum):
    """User-visible ingress operations."""

    PING = "ping"
    HELP = "help"
    CALCULATE = "calculate"
    CONVERT = "convert"
    TIME = "time"
    SEARCH_WEB = "search.web"
    SEARCH_IMAGES = "search.images"
    SEARCH_GIFS = "search.gifs"
    SEARCH_EXPAND = "search.expand"
    LINK_SUMMARIZE = "link.summarize"
    ASK = "ask"
    WHAT_IS_THIS = "what_is_this"
    RESEARCH = "research"
    TRANSLATE = "translate"
    FACT_CHECK = "fact_check"
    QR = "qr"
    EMOJI = "emoji"
    QUOTE = "quote"
    IMAGE_GENERATE = "image.generate"
    IMAGE_EDIT = "image.edit"
    IMAGE_CAPTION = "image.caption"
    IMAGE_EDIT_AI = "image.edit_ai"
    IMAGE_BACKGROUND_REMOVE = "image.background_remove"
    IMAGE_OCR = "image.ocr"
    IMAGE_ASK = "image.ask"
    IMAGE_MEME = "image.meme"
    TRANSCRIBE = "media.transcribe"
    SAVE = "save"
    SAVED_SEARCH = "saved.search"
    SAVED_DELETE = "saved.delete"
    SAVED_SEND_DM = "saved.send_dm"
    SAVED_EXPORT = "saved.export"
    CONTEXT_ADD = "context.add"
    CONTEXT_LIST = "context.list"
    CONTEXT_CLEAR = "context.clear"
    PREFERENCES = "preferences"
    STATUS = "status"
    CODEX_LOGIN = "codex.login"
    SHARE = "share"
    USER_INFO = "user.info"
    FILE_CONVERT = "file.convert"
    WEATHER = "weather"
    REMINDER_CREATE = "reminder.create"
    REMINDER_LIST = "reminder.list"
    REMINDER_CANCEL = "reminder.cancel"


class Visibility(StrEnum):
    """Where a result is intended to be presented."""

    PRIVATE = "private"
    PUBLIC = "public"


class HealthState(StrEnum):
    """Operational state used by the owner-only runtime status view."""

    HEALTHY = "healthy"
    STARTING = "starting"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class ActionKind(StrEnum):
    """Bounded actions that may be attached to a rendered result."""

    SHARE = "share"
    SAVE = "save"
    ASK = "ask"
    TRANSLATE = "translate"
    FACT_CHECK = "fact_check"
    NEXT_PAGE = "next_page"
    PREVIOUS_PAGE = "previous_page"
    EXPAND = "expand"
    REGENERATE = "regenerate"
    REFINE = "refine"
    EDIT = "edit"
    MEME = "meme"
    CLEAR_CONTEXT = "clear_context"
    DELETE = "delete"
    SEND_DM = "send_dm"


class AIProfile(StrEnum):
    """Application intent, deliberately independent of concrete model names."""

    FAST = "fast"
    NORMAL = "normal"
    RESEARCH = "research"
    VISION = "vision"


class QuoteFont(StrEnum):
    """Font families exposed by the deterministic quote-card renderer."""

    SANS = "sans"
    SERIF = "serif"
    MONO = "mono"
    DISPLAY = "display"


class QuoteTextPosition(StrEnum):
    """Horizontal alignment of the quote block within its text area."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class QuoteColorMode(StrEnum):
    """Whether the source image keeps its color."""

    COLOR = "color"
    GRAYSCALE = "grayscale"


class QuoteImageMode(StrEnum):
    """Where the source image is composed into the quote card."""

    LEFT = "left"
    RIGHT = "right"
    BACKGROUND = "background"
    HIDDEN = "hidden"


class SearchKind(StrEnum):
    """Search mode requested by an application capability."""

    WEB = "web"
    IMAGES = "images"
    NEWS = "news"
    VIDEO = "video"
    GIF = "gif"


class Verdict(StrEnum):
    """Descriptive fact-check outcome, not a probability."""

    TRUE = "true"
    MOSTLY_TRUE = "mostly_true"
    MIXED = "mixed"
    MOSTLY_FALSE = "mostly_false"
    FALSE = "false"
    UNVERIFIED = "unverified"


class SavedItemKind(StrEnum):
    """Durable saved-item categories."""

    MESSAGE = "message"
    TEXT = "text"
    SEARCH = "search"
    ASSET = "asset"


class ReminderStatus(StrEnum):
    """Durable reminder lifecycle."""

    PENDING = "pending"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class UserContext:
    """Normalized user identity."""

    user_id: int
    display_name: str
    locale: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Normalized actor and installation-owner facts."""

    user: UserContext
    installation_owner_id: int | None = None
    permissions: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class InteractionContext:
    """Transport-neutral facts about where an interaction occurred."""

    guild_id: int | None
    channel_id: int | None
    surface: str
    public_allowed: bool = False


@dataclass(frozen=True, slots=True)
class AuthenticationChallenge:
    """Short-lived, provider-neutral device-login information."""

    challenge_id: UUID
    verification_url: str
    user_code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """Metadata for an untrusted remote attachment."""

    attachment_id: str
    source_url: str
    filename: str
    declared_content_type: str | None
    declared_size: int


@dataclass(frozen=True, slots=True)
class AssetRef:
    """Reference to validated, application-owned data."""

    asset_id: UUID
    mime_type: str
    size: int
    owner_id: int
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MessageContext:
    """Normalized message data supplied by an interaction."""

    message_id: int
    author_id: int
    author_name: str
    content: str
    channel_id: int | None
    guild_id: int | None
    reply_to_message_id: int | None
    attachments: tuple[AttachmentRef, ...] = ()
    author_avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class ContextItem:
    """Explicitly selected context that may be sent to an AI capability."""

    item_id: UUID
    owner_id: int
    label: str
    text: str | None = None
    message: MessageContext | None = None
    asset: AssetRef | None = None


@dataclass(frozen=True, slots=True)
class SavedItem:
    """Durable owner-scoped saved content."""

    item_id: UUID
    owner_id: int
    kind: SavedItemKind
    title: str | None
    text: str | None
    source_url: str | None
    asset_id: UUID | None
    created_at: datetime
    tags: tuple[str, ...] = ()
    asset_mime_type: str | None = None
    asset_size: int | None = None


@dataclass(frozen=True, slots=True)
class UserPreferences:
    """Persisted user preferences, separate from runtime deployment settings."""

    owner_id: int
    timezone: str = "UTC"
    language: str = "English"
    currency: str = "USD"
    visibility: Visibility = Visibility.PRIVATE
    default_profile: AIProfile = AIProfile.NORMAL
    quote_font: QuoteFont = QuoteFont.SANS
    quote_text_position: QuoteTextPosition = QuoteTextPosition.CENTER
    quote_color_mode: QuoteColorMode = QuoteColorMode.GRAYSCALE
    quote_image_mode: QuoteImageMode = QuoteImageMode.LEFT
    accessibility_plain_text: bool = False
    accessibility_high_contrast: bool = False
    accessibility_reduce_motion: bool = False
    accessibility_verbose: bool = False


@dataclass(frozen=True, slots=True)
class Reminder:
    """Restart-safe scheduled personal action."""

    reminder_id: UUID
    owner_id: int
    due_at_utc: datetime
    payload: str
    status: ReminderStatus
    attempt_count: int = 0
    claimed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class InteractionSession:
    """Short-lived server-side component/session state."""

    session_id: UUID
    owner_id: int
    action: ActionKind
    target_id: UUID | None
    payload: Mapping[str, str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Normalized request entering the application dispatcher."""

    request_id: UUID
    capability: CapabilityName
    actor: ActorContext
    interaction: InteractionContext
    text: str | None = None
    target_message: MessageContext | None = None
    target_user: UserContext | None = None
    attachments: tuple[AttachmentRef, ...] = ()
    context_items: tuple[ContextItem, ...] = ()
    options: Mapping[str, str] = field(default_factory=_empty_string_map)
    session_id: UUID | None = None
    action: ActionKind | None = None
    requested_visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class QuoteStyle:
    """Validated, transport-neutral visual choices for a quote card."""

    font: QuoteFont = QuoteFont.SANS
    text_position: QuoteTextPosition = QuoteTextPosition.CENTER
    color_mode: QuoteColorMode = QuoteColorMode.GRAYSCALE
    image_mode: QuoteImageMode = QuoteImageMode.LEFT


@dataclass(frozen=True, slots=True)
class QuoteCardRequest:
    """One complete quote-card render request after input normalization."""

    quote: str
    author: str
    style: QuoteStyle = field(default_factory=QuoteStyle)


@dataclass(frozen=True, slots=True)
class EmojiRenderRequest:
    """One bounded emoji-to-image request for the local emoji utility."""

    value: str
    size: int = 512


@dataclass(frozen=True, slots=True)
class ToolAction:
    """Safe, bounded action metadata for a renderer."""

    kind: ActionKind
    label: str
    target_id: UUID | None = None
    session_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class UsageInfo:
    """Provider-neutral usage accounting."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Provider-neutral text or multimodal model request."""

    system: str | None
    input: str
    images: tuple[AssetRef, ...] = ()
    response_schema: Mapping[str, object] | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized provider response."""

    text: str
    structured: object | None = None
    usage: UsageInfo | None = None
    provider_metadata: Mapping[str, object] = field(default_factory=_empty_object_map)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Provider-neutral search request."""

    query: str
    kind: SearchKind = SearchKind.WEB
    cursor: str | None = None
    limit: int = 5
    safe_search: str = "moderate"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Raw normalized search-provider hit."""

    title: str
    url: str
    snippet: str | None = None
    source_name: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    """Provider data, intentionally separate from the Discord result model."""

    query: str
    kind: SearchKind
    hits: tuple[SearchHit, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class LinkDocument:
    """Bounded, provider-neutral document fetched from one safe URL."""

    url: str
    title: str | None
    text: str


@dataclass(frozen=True, slots=True)
class CurrencyQuote:
    """Normalized currency conversion data from an exchange-rate provider."""

    amount: float
    base: str
    target: str
    converted: float
    rate: float


@dataclass(frozen=True, slots=True)
class WeatherReport:
    """Normalized current-weather data from a weather provider."""

    location: str
    latitude: float
    longitude: float
    timezone: str
    temperature_c: float
    feels_like_c: float | None
    humidity_percent: float | None
    wind_speed_kmh: float | None
    weather_code: int | None


@dataclass(frozen=True, slots=True)
class OCRResult:
    """Normalized text extracted from an application-owned asset."""

    text: str
    language: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Normalized speech-to-text output from an audio provider."""

    text: str
    language: str | None = None


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    """Provider-neutral image generation intent."""

    prompt: str
    size: str = "1024x1024"
    quality: str = "auto"


@dataclass(frozen=True, slots=True)
class ImageEditRequest:
    """Provider-neutral image-edit intent over one owned source asset."""

    asset: AssetRef
    prompt: str
    size: str = "1024x1024"


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    """Provider-neutral generated image bytes before AssetStore ownership."""

    data: bytes
    mime_type: str


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """Provider/processor-neutral converted file bytes before asset ownership."""

    data: bytes
    mime_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class SearchResultItem:
    """Application-facing search item."""

    title: str
    url: str
    snippet: str | None = None
    source_name: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Citable source reference used by research-style results."""

    title: str
    url: str
    source_name: str | None = None


@dataclass(frozen=True, slots=True)
class TextResult:
    """Generic text result that a renderer can present."""

    text: str
    title: str | None = None
    input_text: str | None = None
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE
    sources: tuple[SourceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class HelpSection:
    """One bounded section in the interface command reference."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HelpResult:
    """Structured help content rendered by the transport adapter."""

    sections: tuple[HelpSection, ...]
    title: str = "Toolbox commands"
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class SearchResults:
    """Application-facing search result."""

    query: str
    items: tuple[SearchResultItem, ...]
    next_cursor: str | None = None
    kind: SearchKind = SearchKind.WEB
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class ImageResult:
    """Application-facing generated or transformed image."""

    asset: AssetRef
    title: str | None = None
    input_text: str | None = None
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class FileResult:
    """Application-facing file result."""

    asset: AssetRef
    filename: str
    title: str | None = None
    input_text: str | None = None
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class ChoiceResult:
    """A bounded choice rendered by an interface adapter."""

    title: str
    choices: tuple[str, ...]
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class FactCheckResult:
    """Structured application result for a claim evaluation."""

    claim: str
    verdict: Verdict
    explanation: str
    sources: tuple[SourceRef, ...]
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class PendingResult:
    """Result for work handed to a bounded background runner."""

    job_id: UUID
    message: str
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class NoAction:
    """Explicitly indicates that no user-facing response is required."""

    reason: str


@dataclass(frozen=True, slots=True)
class ErrorResult:
    """Safe application error result."""

    code: str
    message: str
    retryable: bool = False
    actions: tuple[ToolAction, ...] = ()
    visibility: Visibility = Visibility.PRIVATE


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """One sanitized component health observation."""

    name: str
    state: HealthState
    detail: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Owner-facing operational snapshot without secrets or raw exceptions."""

    checks: tuple[HealthCheck, ...]


type ToolResult = (
    TextResult
    | HelpResult
    | SearchResults
    | ImageResult
    | FileResult
    | ChoiceResult
    | FactCheckResult
    | PendingResult
    | NoAction
    | ErrorResult
)
