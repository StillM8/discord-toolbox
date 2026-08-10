"""SQL user-preference repository."""

from __future__ import annotations

from toolbox.core.contracts import PreferencesRepository
from toolbox.core.models import (
    AIProfile,
    QuoteColorMode,
    QuoteFont,
    QuoteImageMode,
    QuoteTextPosition,
    UserPreferences,
    Visibility,
)
from toolbox.storage.database import Database
from toolbox.storage.models import PreferenceRow


class SQLPreferencesRepository(PreferencesRepository):
    """Load defaults and persist explicit owner preferences."""

    def __init__(self, database: Database, *, default_timezone: str = "UTC") -> None:
        self._database = database
        self._default_timezone = default_timezone

    async def get(self, owner_id: int) -> UserPreferences:
        async with self._database.sessions() as session:
            row = await session.get(PreferenceRow, owner_id)
            if row is None:
                return UserPreferences(owner_id=owner_id, timezone=self._default_timezone)
            return UserPreferences(
                owner_id=row.owner_id,
                timezone=row.timezone,
                language=row.language,
                currency=row.currency,
                visibility=Visibility(row.visibility),
                default_profile=AIProfile(row.default_profile),
                quote_font=QuoteFont(row.quote_font),
                quote_text_position=QuoteTextPosition(row.quote_text_position),
                quote_color_mode=QuoteColorMode(row.quote_color_mode),
                quote_image_mode=QuoteImageMode(row.quote_image_mode),
                accessibility_plain_text=row.accessibility_plain_text,
                accessibility_high_contrast=row.accessibility_high_contrast,
                accessibility_reduce_motion=row.accessibility_reduce_motion,
                accessibility_verbose=row.accessibility_verbose,
            )

    async def save(self, preferences: UserPreferences) -> None:
        async with self._database.sessions() as session:
            row = await session.get(PreferenceRow, preferences.owner_id)
            if row is None:
                row = PreferenceRow(owner_id=preferences.owner_id)
                session.add(row)
            row.timezone = preferences.timezone
            row.language = preferences.language
            row.currency = preferences.currency
            row.visibility = preferences.visibility.value
            row.default_profile = preferences.default_profile.value
            row.quote_font = preferences.quote_font.value
            row.quote_text_position = preferences.quote_text_position.value
            row.quote_color_mode = preferences.quote_color_mode.value
            row.quote_image_mode = preferences.quote_image_mode.value
            row.accessibility_plain_text = preferences.accessibility_plain_text
            row.accessibility_high_contrast = preferences.accessibility_high_contrast
            row.accessibility_reduce_motion = preferences.accessibility_reduce_motion
            row.accessibility_verbose = preferences.accessibility_verbose
            await session.commit()
