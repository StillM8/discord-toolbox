"""Small replaceable contracts used by application modules."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import (
    AIProfile,
    AssetRef,
    AttachmentRef,
    AuthenticationChallenge,
    ContextItem,
    CurrencyQuote,
    EmojiRenderRequest,
    GeneratedFile,
    GeneratedImage,
    HealthReport,
    HealthState,
    ImageEditRequest,
    ImageGenerationRequest,
    InteractionSession,
    LinkDocument,
    LLMRequest,
    LLMResponse,
    OCRResult,
    QuoteCardRequest,
    Reminder,
    SavedItem,
    SearchPage,
    SearchRequest,
    ToolRequest,
    ToolResult,
    TranscriptionResult,
    UserPreferences,
    WeatherReport,
)


class Handler(Protocol):
    """A capability or workflow callable by the ingress dispatcher."""

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute a normalized application request."""

        ...


class AIService(Protocol):
    """General application entry point for language-model work."""

    async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
        """Generate a provider-neutral response for an application profile."""

        ...


class AIAuthenticationService(Protocol):
    """Small boundary for starting an account-authenticated AI login."""

    async def begin_device_login(self) -> AuthenticationChallenge:
        """Start or return the current short-lived device login challenge."""

        ...


class HealthService(Protocol):
    """Small operational status boundary used by the owner-only status view."""

    async def snapshot(self) -> HealthReport:
        """Return sanitized current component states."""

        ...

    def set_component(self, name: str, state: HealthState, detail: str) -> None:
        """Record a lifecycle state without exposing implementation details."""

        ...


class LLMProvider(Protocol):
    """Replaceable provider boundary for text and multimodal reasoning."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a normalized response."""

        ...


class WebSearchProvider(Protocol):
    """Replaceable raw web/image search provider."""

    async def search(self, request: SearchRequest) -> SearchPage:
        """Return normalized provider data, not a Discord result."""

        ...


class GifSearchProvider(Protocol):
    """Optional provider boundary for animated-image search."""

    async def search(self, request: SearchRequest) -> SearchPage:
        """Return normalized GIF search data, not a Discord result."""

        ...


class CurrencyProvider(Protocol):
    """Replaceable exchange-rate lookup boundary."""

    async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
        """Return one normalized conversion quote."""

        ...


class WeatherProvider(Protocol):
    """Replaceable current-weather lookup boundary."""

    async def current(self, location: str) -> WeatherReport:
        """Return normalized current conditions for a human location."""

        ...


class LinkFetcher(Protocol):
    """Controlled URL/document retrieval boundary."""

    async def fetch(self, url: str) -> LinkDocument:
        """Fetch a bounded, sanitized document from a safe URL."""

        ...


class OCRProvider(Protocol):
    """Replaceable OCR engine boundary."""

    async def extract(self, data: bytes, mime_type: str) -> OCRResult:
        ...


class ImageProcessor(Protocol):
    """Deterministic media transformation service used by image capabilities."""

    async def transform(
        self,
        data: bytes,
        operation: str,
        options: Mapping[str, str] | None = None,
        *,
        max_pixels: int = 20_000_000,
    ) -> bytes:
        """Transform bounded image bytes without external provider state."""

        ...


class QuoteCardProcessor(Protocol):
    """Deterministic local renderer for reference-style quote cards."""

    async def render(
        self,
        request: QuoteCardRequest,
        image_data: bytes | None = None,
    ) -> bytes:
        """Render one quote, attribution, style, and optional image."""

        ...


class QuotePreviewService(Protocol):
    """Render a quote preview from one normalized application request."""

    async def render_preview(self, request: ToolRequest) -> bytes:
        """Return preview bytes without creating a durable/shareable result."""

        ...


class EmojiProcessor(Protocol):
    """Deterministic local renderer for Unicode or downloaded custom emojis."""

    async def render(
        self,
        request: EmojiRenderRequest,
        image_data: bytes | None = None,
    ) -> bytes:
        """Render one emoji without Discord or provider knowledge."""

        ...


class TranscriptionProvider(Protocol):
    """Replaceable speech-to-text provider boundary."""

    async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
        ...


class ImageGenerationProvider(Protocol):
    """Replaceable image-generation boundary."""

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        ...


class ImageEditingProvider(Protocol):
    """Replaceable provider boundary for editing an existing image."""

    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        ...


class BackgroundRemovalProvider(Protocol):
    """Optional local/replaceable foreground-segmentation boundary."""

    async def remove(self, data: bytes, mime_type: str) -> GeneratedImage:
        """Return a transparent PNG or a normalized provider failure."""

        ...


class FileProcessor(Protocol):
    """Bounded local file conversion boundary."""

    async def convert(
        self,
        data: bytes,
        *,
        source_mime: str,
        source_filename: str,
        target_format: str,
    ) -> GeneratedFile:
        """Convert one validated application-owned file."""

        ...


class AttachmentIngestor(Protocol):
    """Validate and copy one remote attachment into application-owned storage."""

    async def ingest(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        ...


class ImageAttachmentIngestor(Protocol):
    """Validate and transform one remote image before storing it once."""

    async def ingest(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        ...

    async def ingest_transformed(
        self,
        attachment: AttachmentRef,
        owner_id: int,
        *,
        operation: str,
        options: Mapping[str, str] | None = None,
    ) -> AssetRef:
        """Download, validate, transform, and own one image in one pipeline."""

        ...


class RawAttachmentIngestor(Protocol):
    """Validate and store a non-image attachment without image re-encoding."""

    async def ingest_raw(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        ...


class AssetStore(Protocol):
    """Storage boundary for validated application-owned binary data."""

    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        """Store bytes and return an opaque asset reference."""

        ...

    async def read(self, asset: AssetRef) -> bytes:
        """Read bytes belonging to an existing asset."""

        ...

    async def delete(self, asset: AssetRef) -> None:
        """Delete an asset owned by the application."""

        ...


class ContextStore(Protocol):
    """Temporary explicit context-basket boundary."""

    async def add(self, item: ContextItem) -> None:
        """Add or replace one owned context item."""

        ...

    async def list(self, owner_id: int) -> Sequence[ContextItem]:
        """List bounded context items for one owner."""

        ...

    async def clear(self, owner_id: int) -> None:
        """Clear one owner's temporary context."""

        ...


class SavedItemRepository(Protocol):
    """Durable saved-item storage."""

    async def save(self, item: SavedItem) -> None:
        ...

    async def search(self, owner_id: int, query: str) -> Sequence[SavedItem]:
        ...

    async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
        """Load one item only when it belongs to the owner."""

        ...

    async def delete(self, owner_id: int, item_id: UUID) -> None:
        ...


class SavedItemDelivery(Protocol):
    """Transport-neutral delivery of one already-authorized saved item."""

    async def deliver(self, item: SavedItem) -> None:
        ...


class PreferencesRepository(Protocol):
    """Owner-scoped preference storage."""

    async def get(self, owner_id: int) -> UserPreferences:
        ...

    async def save(self, preferences: UserPreferences) -> None:
        ...


class ReminderRepository(Protocol):
    """Durable reminder storage and claiming boundary."""

    async def create(self, reminder: Reminder) -> None:
        ...

    async def due(self, now: datetime, limit: int = 20) -> Sequence[Reminder]:
        ...

    async def claim(self, reminder_id: UUID, now: datetime) -> bool:
        ...

    async def mark_delivered(self, reminder_id: UUID) -> None:
        ...

    async def mark_failed(self, reminder_id: UUID, now: datetime) -> None:
        ...

    async def list_for_owner(self, owner_id: int) -> Sequence[Reminder]:
        ...

    async def cancel(self, owner_id: int, reminder_id: UUID) -> None:
        ...


class ReminderDelivery(Protocol):
    """Transport-independent delivery of one claimed reminder."""

    async def deliver(self, reminder: Reminder) -> None:
        ...


class SessionStore(Protocol):
    """Opaque, owner-authorized component session storage."""

    async def create(self, session: InteractionSession) -> None:
        ...

    async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
        ...

    async def delete(self, owner_id: int, session_id: UUID) -> None:
        ...


class Clock(Protocol):
    """Injectable time source for expiry and scheduling tests."""

    def now(self) -> datetime:
        """Return timezone-aware UTC time."""

        ...


class JobRunner(Protocol):
    """Bounded background execution boundary."""

    async def submit(self, operation: Awaitable[object]) -> UUID:
        """Submit an application-owned awaitable operation."""

        ...


class ResultRenderer(Protocol):
    """Transport-specific result presentation contract."""

    async def render(self, interaction: object, result: ToolResult) -> None:
        """Render a generic result at an interface boundary."""

        ...
