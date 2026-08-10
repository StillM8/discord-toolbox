"""Composition root: construct and connect Toolbox's long-lived components."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from dataclasses import dataclass, field
from typing import Protocol, cast

from toolbox.capabilities.ask import AskCapability
from toolbox.capabilities.background_removal import BackgroundRemovalCapability
from toolbox.capabilities.calculate import CalculateCapability
from toolbox.capabilities.codex_login import CodexLoginCapability
from toolbox.capabilities.convert import ConvertCapability
from toolbox.capabilities.emoji import EmojiCapability
from toolbox.capabilities.explain import WhatIsThisCapability
from toolbox.capabilities.file_convert import FileConvertCapability
from toolbox.capabilities.help import HelpCapability
from toolbox.capabilities.image_edit import ImageEditCapability
from toolbox.capabilities.image_generation import ImageGenerationCapability
from toolbox.capabilities.image_question import ImageQuestionCapability
from toolbox.capabilities.media import ImageAssetCapability, OCRCapability
from toolbox.capabilities.personal import (
    ContextAddCapability,
    ContextClearCapability,
    ContextListCapability,
    SaveCapability,
    SavedDeleteCapability,
    SavedSearchCapability,
    SavedSendDMCapability,
    ShareCapability,
)
from toolbox.capabilities.ping import PingCapability
from toolbox.capabilities.preferences import PreferencesCapability
from toolbox.capabilities.qr import QRCapability
from toolbox.capabilities.quote import QuoteCapability
from toolbox.capabilities.reminders import (
    ReminderCancelCapability,
    ReminderCreateCapability,
    ReminderListCapability,
)
from toolbox.capabilities.search import SearchCapability
from toolbox.capabilities.search_expand import SearchExpandCapability
from toolbox.capabilities.status import StatusCapability
from toolbox.capabilities.time import TimeConversionCapability
from toolbox.capabilities.transcribe import TranscribeCapability
from toolbox.capabilities.translate import TranslateCapability
from toolbox.capabilities.user_info import UserInfoCapability
from toolbox.capabilities.vault import VaultExportCapability
from toolbox.capabilities.weather import WeatherCapability
from toolbox.config.settings import Settings
from toolbox.core.contracts import ImageEditingProvider, LLMProvider
from toolbox.core.models import AIProfile, CapabilityName, HealthState
from toolbox.core.result_codec import ResultCodec
from toolbox.infrastructure.assets import LocalAssetStore
from toolbox.infrastructure.attachments import AttachmentIngestor
from toolbox.infrastructure.clock import SystemClock
from toolbox.infrastructure.file_processor import LocalFileProcessor
from toolbox.infrastructure.health import RuntimeHealthService
from toolbox.infrastructure.http import ManagedHttpClient
from toolbox.infrastructure.jobs import SimpleJobRunner
from toolbox.infrastructure.logging import configure_logging, log_event
from toolbox.infrastructure.media import ImageProcessor as LocalImageProcessor
from toolbox.infrastructure.media import LocalEmojiProcessor, LocalQuoteCardProcessor
from toolbox.infrastructure.scheduler import ReminderScheduler
from toolbox.interfaces.discord.bot import ToolboxBot
from toolbox.interfaces.discord.delivery import (
    DiscordReminderDelivery,
    DiscordSavedItemDelivery,
)
from toolbox.interfaces.discord.mapper import DiscordMapper
from toolbox.interfaces.discord.renderer import DiscordRenderer
from toolbox.providers.audio.faster_whisper import FasterWhisperTranscriptionProvider
from toolbox.providers.audio.openai import OpenAITranscriptionClient, OpenAITranscriptionProvider
from toolbox.providers.audio.unavailable import UnavailableTranscriptionProvider
from toolbox.providers.currency.frankfurter import FrankfurterCurrencyProvider
from toolbox.providers.images.codex import CodexImageProvider
from toolbox.providers.images.openai import OpenAIImageProvider, OpenAIImagesClient
from toolbox.providers.images.rembg import RembgBackgroundRemovalProvider
from toolbox.providers.images.router import ImageProviderRouter
from toolbox.providers.images.unavailable_background import UnavailableBackgroundRemovalProvider
from toolbox.providers.links.http import HttpLinkFetcher
from toolbox.providers.llm.codex import CodexProvider
from toolbox.providers.llm.openai_responses import OpenAIClient, OpenAIResponsesProvider
from toolbox.providers.llm.router import AIRouter
from toolbox.providers.ocr.tesseract import TesseractOCRProvider
from toolbox.providers.search.giphy import GiphySearchProvider
from toolbox.providers.search.searxng import SearXNGSearchProvider
from toolbox.providers.search.unavailable import UnavailableGifSearchProvider
from toolbox.providers.weather.open_meteo import OpenMeteoWeatherProvider
from toolbox.storage.database import Database
from toolbox.storage.repositories.context import SQLContextStore
from toolbox.storage.repositories.preferences import SQLPreferencesRepository
from toolbox.storage.repositories.reminders import SQLReminderRepository
from toolbox.storage.repositories.saved import SQLSavedItemRepository
from toolbox.storage.repositories.sessions import SQLSessionStore
from toolbox.workflows.fact_check import FactCheckWorkflow
from toolbox.workflows.link_summary import LinkSummaryWorkflow
from toolbox.workflows.research import ResearchWorkflow

from .dispatcher import Dispatcher


class OpenAIClientLifecycle(Protocol):
    """Small lifecycle surface needed from the optional OpenAI SDK client."""

    async def close(self) -> None:
        """Close the client-owned HTTP resources."""

        ...


@dataclass(slots=True)
class Runtime:
    """Long-lived runtime objects with explicit startup/shutdown ownership."""

    dispatcher: Dispatcher
    bot: ToolboxBot
    database: Database
    http: ManagedHttpClient
    assets: LocalAssetStore
    codex_providers: tuple[CodexProvider, ...]
    jobs: SimpleJobRunner
    scheduler: ReminderScheduler
    health: RuntimeHealthService
    openai_client: OpenAIClientLifecycle | None = None
    _probe_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def start(self) -> None:
        """Initialize resources that require asynchronous setup."""

        runtime_logger = logging.getLogger("toolbox.runtime")
        log_event(runtime_logger, "runtime_starting")
        log_event(runtime_logger, "assets_initializing")
        await self.assets.initialize()
        self.health.set_component("Assets", HealthState.HEALTHY, "Asset directory is writable")
        log_event(runtime_logger, "assets_ready")
        log_event(runtime_logger, "database_migrating")
        await self.database.migrate()
        self.health.set_component("SQLite", HealthState.HEALTHY, "Alembic schema is ready")
        log_event(runtime_logger, "database_ready")
        await self.scheduler.start()
        log_event(runtime_logger, "scheduler_started")
        self._probe_task = asyncio.create_task(
            self.refresh_codex_health(),
            name="toolbox-codex-probe",
        )
        log_event(runtime_logger, "codex_probe_started_in_background")

    async def refresh_codex_health(self) -> None:
        """Probe the isolated Codex session without generating or executing tools."""

        provider = self.codex_providers[1] if len(self.codex_providers) > 1 else None
        if provider is None or not provider.auth_state_available:
            self.health.set_codex_probe(
                HealthState.DEGRADED,
                "CODEX_HOME is not authenticated yet",
            )
            self.health.set_codex_image_probe(
                HealthState.UNAVAILABLE,
                "Codex ImageGen cannot be probed before authentication",
            )
            return
        if await provider.probe():
            self.health.set_codex_probe(
                HealthState.HEALTHY,
                "Authenticated Codex text probe succeeded",
            )
            if await provider.probe_image():
                self.health.set_codex_image_probe(
                    HealthState.HEALTHY,
                    "Codex ImageGen returned a retrievable artifact",
                )
            else:
                self.health.set_codex_image_probe(
                    HealthState.UNAVAILABLE,
                    "Codex text works but ImageGen did not return an artifact",
                )
        else:
            self.health.set_codex_probe(
                HealthState.UNAVAILABLE,
                "Codex session initialization failed",
            )
            self.health.set_codex_image_probe(
                HealthState.UNAVAILABLE,
                "Codex ImageGen cannot be probed while text is unavailable",
            )

    async def close(self) -> None:
        """Close resources in the reverse direction of construction."""

        if self._probe_task is not None:
            self._probe_task.cancel()
            await asyncio.gather(self._probe_task, return_exceptions=True)
            self._probe_task = None
        await self.scheduler.stop()
        await self.jobs.shutdown()
        await self.bot.close()
        for provider in reversed(self.codex_providers):
            await provider.close()
        if self.openai_client is not None:
            await self.openai_client.close()
        await self.http.close()
        await self.database.close()


def build_runtime(settings: Settings | None = None) -> Runtime:
    """Build the complete current application graph in one composition root."""

    runtime_settings = settings or Settings()
    clock = SystemClock()
    http = ManagedHttpClient()
    database = Database(runtime_settings.database_url)
    assets = LocalAssetStore(
        runtime_settings.asset_directory,
        clock,
        max_bytes=runtime_settings.max_attachment_bytes,
    )
    attachment_ingestor = AttachmentIngestor(
        http.client,
        assets,
        max_bytes=runtime_settings.max_attachment_bytes,
    )
    image_processor = LocalImageProcessor()
    file_processor = LocalFileProcessor(max_bytes=runtime_settings.max_attachment_bytes)

    context_store = SQLContextStore(
        database,
        clock,
        max_items=runtime_settings.max_context_items,
        ttl_seconds=runtime_settings.context_ttl_seconds,
    )
    saved_items = SQLSavedItemRepository(database)
    preferences = SQLPreferencesRepository(
        database,
        default_timezone=runtime_settings.default_timezone,
    )
    sessions = SQLSessionStore(database, clock)
    reminders = SQLReminderRepository(
        database,
        max_attempts=runtime_settings.max_reminder_attempts,
        claim_timeout_seconds=runtime_settings.reminder_claim_timeout_seconds,
    )

    codex_providers = tuple(
        CodexProvider(
            command=runtime_settings.codex_command,
            model=runtime_settings.ai_profiles[profile].model,
            effort=runtime_settings.ai_profiles[profile].effort,
            timeout_seconds=runtime_settings.codex_timeout_seconds,
            image_timeout_seconds=runtime_settings.codex_image_timeout_seconds,
            image_effort=runtime_settings.codex_image_effort,
            assets=assets,
            environment={"CODEX_HOME": str(runtime_settings.codex_home)},
            max_concurrency=runtime_settings.max_codex_concurrency,
            max_image_bytes=runtime_settings.max_attachment_bytes,
        )
        for profile in (AIProfile.FAST, AIProfile.NORMAL, AIProfile.RESEARCH)
    )
    providers: dict[str, LLMProvider] = {
        "codex_fast": codex_providers[0],
        "codex_normal": codex_providers[1],
        "codex_research": codex_providers[2],
    }
    openai_client: OpenAIClientLifecycle | None = None
    openai_api_key = (
        runtime_settings.openai_api_key.get_secret_value().strip()
        if runtime_settings.openai_api_key is not None
        else ""
    )
    if openai_api_key:
        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError:
            log_event(
                logging.getLogger("toolbox.bootstrap"),
                "optional_openai_sdk_unavailable",
                level=logging.WARNING,
            )
        else:
            concrete_openai_client = AsyncOpenAI(
                api_key=openai_api_key,
            )
            openai_client = cast(OpenAIClientLifecycle, concrete_openai_client)
            providers["openai_responses"] = OpenAIResponsesProvider(
                client=cast(OpenAIClient, concrete_openai_client),
                model=runtime_settings.openai_vision_model,
                assets=assets,
                timeout_seconds=runtime_settings.codex_timeout_seconds,
            )
            providers["openai_fallback"] = OpenAIResponsesProvider(
                client=cast(OpenAIClient, concrete_openai_client),
                model=runtime_settings.openai_fallback_model,
                assets=assets,
                timeout_seconds=runtime_settings.codex_timeout_seconds,
            )

    local_transcription_available = (
        runtime_settings.enable_local_transcription
        and importlib.util.find_spec("faster_whisper") is not None
    )
    background_removal_available = (
        runtime_settings.enable_local_background_removal
        and importlib.util.find_spec("rembg") is not None
    )
    giphy_api_key = (
        runtime_settings.giphy_api_key.get_secret_value().strip()
        if runtime_settings.giphy_api_key is not None
        else ""
    )
    health = RuntimeHealthService(
        http=http.client,
        searxng_url=runtime_settings.searxng_url,
        asset_directory=runtime_settings.asset_directory,
        codex_home=runtime_settings.codex_home,
        codex_command=runtime_settings.codex_command,
        openai_configured=openai_client is not None,
        paid_image_fallback_enabled=runtime_settings.enable_paid_image_fallback,
        transcription_enabled=(
            local_transcription_available or runtime_settings.enable_openai_transcription
        ),
        local_transcription_enabled=local_transcription_available,
        codex_image_generation_enabled=False,
        giphy_configured=runtime_settings.enable_giphy and bool(giphy_api_key),
        background_removal_enabled=background_removal_available,
    )

    ai_profiles = {
        profile: spec.provider for profile, spec in runtime_settings.ai_profiles.items()
    }
    if openai_client is None:
        ai_profiles[AIProfile.VISION] = "codex_normal"
    ai = AIRouter(
        profiles=ai_profiles,
        providers=providers,
        fallbacks=(
            {
                "codex_fast": "openai_fallback",
                "codex_normal": "openai_fallback",
                "codex_research": "openai_fallback",
            }
            if runtime_settings.openai_fallback_enabled and openai_client is not None
            else {}
        ),
    )

    search_provider = SearXNGSearchProvider(
        http.client,
        base_url=runtime_settings.searxng_url,
    )
    gif_search_provider: GiphySearchProvider | UnavailableGifSearchProvider
    if runtime_settings.enable_giphy and giphy_api_key:
        gif_search_provider = GiphySearchProvider(
            http.client,
            api_key=giphy_api_key,
        )
    else:
        gif_search_provider = UnavailableGifSearchProvider()
    dispatcher = Dispatcher()
    dispatcher.register(CapabilityName.PING, PingCapability())
    dispatcher.register(CapabilityName.HELP, HelpCapability())
    dispatcher.register(CapabilityName.CALCULATE, CalculateCapability())
    currency_provider = FrankfurterCurrencyProvider(http.client)
    dispatcher.register(CapabilityName.CONVERT, ConvertCapability(currency=currency_provider))
    dispatcher.register(CapabilityName.TIME, TimeConversionCapability(clock))
    dispatcher.register(
        CapabilityName.SEARCH_WEB,
        SearchCapability(
            search_provider,
            max_results=runtime_settings.max_search_results,
            sessions=sessions,
            clock=clock,
            session_ttl_seconds=runtime_settings.session_ttl_seconds,
        ),
    )
    dispatcher.register(
        CapabilityName.SEARCH_IMAGES,
        SearchCapability(
            search_provider,
            max_results=runtime_settings.max_search_results,
            sessions=sessions,
            clock=clock,
            session_ttl_seconds=runtime_settings.session_ttl_seconds,
        ),
    )
    dispatcher.register(
        CapabilityName.SEARCH_GIFS,
        SearchCapability(
            gif_search_provider,
            max_results=runtime_settings.max_search_results,
            sessions=sessions,
            clock=clock,
            session_ttl_seconds=runtime_settings.session_ttl_seconds,
        ),
    )
    dispatcher.register(CapabilityName.ASK, AskCapability(ai, context_store=context_store))
    dispatcher.register(CapabilityName.WHAT_IS_THIS, WhatIsThisCapability(ai))
    dispatcher.register(CapabilityName.RESEARCH, ResearchWorkflow(search=search_provider, ai=ai))
    dispatcher.register(
        CapabilityName.IMAGE_ASK,
        ImageQuestionCapability(ai, assets, attachment_ingestor),
    )
    dispatcher.register(CapabilityName.TRANSLATE, TranslateCapability(ai))
    link_fetcher = HttpLinkFetcher(http.client)
    dispatcher.register(
        CapabilityName.LINK_SUMMARIZE,
        LinkSummaryWorkflow(fetcher=link_fetcher, ai=ai),
    )
    dispatcher.register(
        CapabilityName.SEARCH_EXPAND,
        SearchExpandCapability(fetcher=link_fetcher, sessions=sessions),
    )
    dispatcher.register(
        CapabilityName.WEATHER,
        WeatherCapability(OpenMeteoWeatherProvider(http.client)),
    )
    dispatcher.register(CapabilityName.QR, QRCapability(assets))
    dispatcher.register(
        CapabilityName.EMOJI,
        EmojiCapability(LocalEmojiProcessor(), assets, attachment_ingestor),
    )
    quote_capability = QuoteCapability(
        LocalQuoteCardProcessor(),
        assets,
        attachment_ingestor,
        preferences,
    )
    dispatcher.register(CapabilityName.QUOTE, quote_capability)
    dispatcher.register(
        CapabilityName.FILE_CONVERT,
        FileConvertCapability(assets, attachment_ingestor, file_processor),
    )
    dispatcher.register(
        CapabilityName.IMAGE_EDIT,
        ImageAssetCapability(assets, attachment_ingestor, image_processor),
    )
    dispatcher.register(
        CapabilityName.IMAGE_MEME,
        ImageAssetCapability(assets, attachment_ingestor, image_processor),
    )
    dispatcher.register(
        CapabilityName.IMAGE_CAPTION,
        ImageAssetCapability(assets, attachment_ingestor, image_processor),
    )
    dispatcher.register(
        CapabilityName.IMAGE_OCR,
        OCRCapability(assets, TesseractOCRProvider(), attachment_ingestor),
    )
    transcription_provider: (
        UnavailableTranscriptionProvider
        | OpenAITranscriptionProvider
        | FasterWhisperTranscriptionProvider
    ) = UnavailableTranscriptionProvider()
    if local_transcription_available:
        transcription_provider = FasterWhisperTranscriptionProvider(assets)
    elif openai_client is not None and runtime_settings.enable_openai_transcription:
        transcription_provider = OpenAITranscriptionProvider(
            client=cast(OpenAITranscriptionClient, openai_client),
            assets=assets,
            model=runtime_settings.openai_transcription_model,
            timeout_seconds=runtime_settings.codex_timeout_seconds * 2,
        )
    dispatcher.register(
        CapabilityName.TRANSCRIBE,
        TranscribeCapability(transcription_provider, assets, attachment_ingestor),
    )
    background_provider = (
        RembgBackgroundRemovalProvider()
        if background_removal_available
        else UnavailableBackgroundRemovalProvider()
    )
    dispatcher.register(
        CapabilityName.IMAGE_BACKGROUND_REMOVE,
        BackgroundRemovalCapability(background_provider, assets, attachment_ingestor),
    )
    paid_image_provider: OpenAIImageProvider | None = None
    if openai_client is not None and runtime_settings.enable_paid_image_fallback:
        paid_image_provider = OpenAIImageProvider(
            client=cast(OpenAIImagesClient, openai_client),
            model=runtime_settings.openai_image_model,
            http=http.client,
            assets=assets,
            timeout_seconds=runtime_settings.codex_timeout_seconds * 2,
        )
    image_provider = ImageProviderRouter(
        primary=CodexImageProvider(codex_providers[1]),
        fallback=paid_image_provider,
    )
    dispatcher.register(
        CapabilityName.IMAGE_GENERATE,
        ImageGenerationCapability(image_provider, assets),
    )
    dispatcher.register(
        CapabilityName.IMAGE_EDIT_AI,
        ImageEditCapability(
            cast(ImageEditingProvider, image_provider),
            assets,
            attachment_ingestor,
            local_processor=image_processor,
        ),
    )
    dispatcher.register(
        CapabilityName.FACT_CHECK,
        FactCheckWorkflow(search=search_provider, ai=ai, fetcher=link_fetcher),
    )
    dispatcher.register(CapabilityName.CONTEXT_CLEAR, ContextClearCapability(context_store))
    dispatcher.register(CapabilityName.CONTEXT_LIST, ContextListCapability(context_store))
    dispatcher.register(CapabilityName.SAVED_SEARCH, SavedSearchCapability(saved_items))
    dispatcher.register(CapabilityName.SAVED_DELETE, SavedDeleteCapability(saved_items, assets))
    dispatcher.register(
        CapabilityName.CONTEXT_ADD,
        ContextAddCapability(context_store, attachment_ingestor),
    )
    dispatcher.register(CapabilityName.PREFERENCES, PreferencesCapability(preferences))
    dispatcher.register(
        CapabilityName.STATUS,
        StatusCapability(health, owner_id=runtime_settings.owner_id),
    )
    dispatcher.register(
        CapabilityName.CODEX_LOGIN,
        CodexLoginCapability(codex_providers[1], owner_id=runtime_settings.owner_id),
    )
    dispatcher.register(CapabilityName.USER_INFO, UserInfoCapability())
    dispatcher.register(CapabilityName.SHARE, ShareCapability(sessions, ResultCodec()))
    dispatcher.register(
        CapabilityName.REMINDER_CREATE,
        ReminderCreateCapability(reminders, clock, preferences),
    )
    dispatcher.register(CapabilityName.REMINDER_LIST, ReminderListCapability(reminders))
    dispatcher.register(CapabilityName.REMINDER_CANCEL, ReminderCancelCapability(reminders))

    mapper = DiscordMapper()
    renderer = DiscordRenderer(
        sessions=sessions,
        clock=clock,
        assets=assets,
        preferences=preferences,
        quote_preview=quote_capability,
        mapper=mapper,
        session_ttl_seconds=runtime_settings.session_ttl_seconds,
    )
    bot = ToolboxBot(
        dispatcher=dispatcher,
        mapper=mapper,
        renderer=renderer,
        health=health,
    )
    saved_delivery = DiscordSavedItemDelivery(bot, renderer)
    dispatcher.register(
        CapabilityName.SAVE,
        SaveCapability(
            saved_items,
            clock,
            ingestor=attachment_ingestor,
            delivery=saved_delivery,
        ),
    )
    dispatcher.register(
        CapabilityName.SAVED_SEND_DM,
        SavedSendDMCapability(saved_items, sessions, saved_delivery),
    )
    dispatcher.register(CapabilityName.SAVED_EXPORT, VaultExportCapability(saved_items, assets))
    jobs = SimpleJobRunner(max_concurrency=4)
    scheduler = ReminderScheduler(
        reminders,
        DiscordReminderDelivery(bot, renderer),
        jobs,
        clock,
    )
    runtime = Runtime(
        dispatcher=dispatcher,
        bot=bot,
        database=database,
        http=http,
        assets=assets,
        codex_providers=codex_providers,
        jobs=jobs,
        scheduler=scheduler,
        health=health,
        openai_client=openai_client,
    )

    async def refresh_codex_health() -> None:
        await runtime.refresh_codex_health()

    codex_providers[1].set_authentication_callback(refresh_codex_health)
    return runtime


async def main() -> None:
    """Start and gracefully close the Discord transport."""

    settings = Settings()
    configure_logging(settings.log_level)
    runtime = build_runtime(settings)
    await runtime.start()
    try:
        log_event(logging.getLogger("toolbox.bootstrap"), "discord_starting")
        await runtime.bot.start(settings.discord_token_value())
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
