"""Bounded local image processing with no Discord or provider knowledge."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, cast

import pillow_heif  # pyright: ignore[reportMissingTypeStubs]
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from toolbox.core.errors import AssetRejected, InvalidRequest
from toolbox.core.models import (
    EmojiRenderRequest,
    QuoteCardRequest,
    QuoteColorMode,
    QuoteFont,
    QuoteImageMode,
    QuoteTextPosition,
)
from toolbox.infrastructure.logging import log_event

register_heif_opener = cast(
    Callable[..., None],
    getattr(cast(Any, pillow_heif), "register_heif_opener"),
)
register_heif_opener()

_logger = logging.getLogger("toolbox.media")


def _caption_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        # Pillow 12's scalable default font keeps the feature usable in
        # minimal images even when a system font is not installed.
        return ImageFont.load_default(size=size)


def _wrap_caption_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        elif current:
            lines.append(current)
            current = word
        else:
            lines.append(word[:30])
    if current:
        lines.append(current)
    return lines or [text[:30]]


class ImageProcessor:
    """Perform small deterministic image transformations in a worker thread."""

    def sanitize(self, data: bytes, *, max_pixels: int = 20_000_000) -> bytes:
        return self._run(data, "sanitize", {}, max_pixels=max_pixels)

    async def transform(
        self,
        data: bytes,
        operation: str,
        options: Mapping[str, str] | None = None,
        *,
        max_pixels: int = 20_000_000,
    ) -> bytes:
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                self._run,
                data,
                operation,
                options or {},
                max_pixels=max_pixels,
            )
        except Exception:
            log_event(
                _logger,
                "image_transform_failed",
                level=logging.WARNING,
                operation=operation,
                input_bytes=len(data),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                exc_info=True,
            )
            raise
        log_event(
            _logger,
            "image_transform_completed",
            operation=operation,
            input_bytes=len(data),
            output_bytes=len(result),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return result

    @staticmethod
    def _run(
        data: bytes,
        operation: str,
        options: Mapping[str, str],
        *,
        max_pixels: int,
    ) -> bytes:
        if not data:
            raise AssetRejected
        try:
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                if source.width * source.height > max_pixels:
                    raise AssetRejected
                image = ImageOps.exif_transpose(source).convert("RGBA")
        except (AssetRejected, OSError, ValueError) as error:
            if isinstance(error, AssetRejected):
                raise
            raise AssetRejected from error

        normalized = operation.lower().strip()
        if normalized == "sanitize":
            pass
        elif normalized == "resize":
            image.thumbnail(
                (
                    ImageProcessor._positive_int(options.get("width"), 2_048),
                    ImageProcessor._positive_int(options.get("height"), 2_048),
                ),
                Image.Resampling.LANCZOS,
            )
        elif normalized == "rotate":
            image = image.rotate(
                ImageProcessor._bounded_int(options.get("degrees"), 90, -360, 360),
                expand=True,
            )
        elif normalized == "mirror":
            image = ImageOps.mirror(image)
        elif normalized == "grayscale":
            image = ImageOps.grayscale(image).convert("RGBA")
        elif normalized == "blur":
            image = image.filter(
                ImageFilter.GaussianBlur(
                    ImageProcessor._bounded_float(options.get("radius"), 3.0, 0.0, 50.0)
                )
            )
        elif normalized == "pixelate":
            image = ImageProcessor._pixelate(image, options)
        elif normalized == "deepfry":
            image = ImageEnhance.Contrast(image).enhance(2.0)
            image = ImageEnhance.Color(image).enhance(1.8)
            image = ImageEnhance.Sharpness(image).enhance(2.5)
        elif normalized == "caption":
            image = ImageProcessor._caption(image, options)
        elif normalized == "meme":
            image = ImageProcessor._meme(image, options)
        else:
            raise InvalidRequest

        output = io.BytesIO()
        # ``optimize=True`` can spend tens of seconds searching for a smaller
        # PNG on large user uploads.  A bounded compression level keeps the
        # local utility responsive; the asset-size limit remains enforced by
        # the asset store and attachment ingestor.
        image.save(output, format="PNG", compress_level=6)
        return output.getvalue()

    @staticmethod
    def _pixelate(image: Image.Image, options: Mapping[str, str]) -> Image.Image:
        block = ImageProcessor._bounded_int(options.get("block"), 12, 2, 100)
        small = image.resize(  # pyright: ignore[reportUnknownMemberType]
            (max(1, image.width // block), max(1, image.height // block)),
            Image.Resampling.NEAREST,
        )
        return small.resize(  # pyright: ignore[reportUnknownMemberType]
            image.size,
            Image.Resampling.NEAREST,
        )

    @staticmethod
    def _meme(image: Image.Image, options: Mapping[str, str]) -> Image.Image:
        top = options.get("top", "").strip()[:200]
        bottom = options.get("bottom", "").strip()[:200]
        caption = options.get("caption", "").strip()[:200]
        if not top and not bottom and not caption:
            raise InvalidRequest

        canvas_size = ImageProcessor._meme_canvas_size(options)
        canvas = ImageProcessor._fit_to_canvas(image, canvas_size)
        panel_height = 0
        if caption:
            canvas, panel_height = ImageProcessor._caption_panel(canvas, caption)
        draw = ImageDraw.Draw(canvas)
        margin = max(24, round(canvas.width * 0.03))
        size = ImageProcessor._meme_font_size(canvas.width)
        font = ImageProcessor._meme_font(size)
        stroke_width = max(3, round(size * 0.04))
        line_height = size + max(6, round(size * 0.15))
        max_width = canvas.width - (margin * 2)

        captions = ((top, True), (bottom, False))
        for text, is_top in captions:
            if not text:
                continue
            lines = ImageProcessor._wrap_meme_text(draw, text, font, max_width)[:3]
            text_height = line_height * len(lines)
            y = panel_height + margin if is_top else canvas.height - margin - text_height
            for line_index, line in enumerate(lines):
                box = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
                x = max(margin, (canvas.width - (box[2] - box[0])) // 2)
                draw.text(
                    (x, y + line_index * line_height),
                    line,
                    fill="white",
                    font=font,
                    stroke_width=stroke_width,
                    stroke_fill="black",
                )
        return canvas

    @staticmethod
    def _caption(image: Image.Image, options: Mapping[str, str]) -> Image.Image:
        caption = options.get("caption", "").strip()[:200]
        if not caption:
            raise InvalidRequest
        normalized = ImageProcessor._fit_to_canvas(
            image,
            ImageProcessor._meme_canvas_size(options),
        )
        canvas, _ = ImageProcessor._caption_panel(normalized, caption)
        return canvas

    @staticmethod
    def _caption_panel(image: Image.Image, caption: str) -> tuple[Image.Image, int]:
        margin = max(32, round(image.width * 0.04))
        font = ImageProcessor._meme_font(max(48, min(96, round(image.width * 0.05))))
        draw = ImageDraw.Draw(image)
        lines = ImageProcessor._wrap_meme_text(draw, caption, font, image.width - (margin * 2))[:3]
        line_height = max(58, round(image.width * 0.055))
        panel_height = max(140, margin + (line_height * len(lines)) + margin)
        canvas = Image.new("RGBA", (image.width, image.height + panel_height), "#111827")
        draw = ImageDraw.Draw(canvas)
        for index, line in enumerate(lines):
            box = draw.textbbox((0, 0), line, font=font)
            x = max(margin, (image.width - (box[2] - box[0])) // 2)
            draw.text(
                (x, margin + index * line_height),
                line,
                fill="#F8FAFC",
                font=font,
            )
        canvas.alpha_composite(image, dest=(0, panel_height))
        return canvas, panel_height

    @staticmethod
    def _meme_canvas_size(options: Mapping[str, str]) -> tuple[int, int]:
        resolution = options.get("resolution", "720p").strip().lower()
        if resolution in {"720", "720p"}:
            return (1_280, 720)
        if resolution in {"1080", "1080p"}:
            return (1_920, 1_080)
        raise InvalidRequest

    @staticmethod
    def _fit_to_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
        fitted = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size, (0, 0, 0, 255))
        offset = ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2)
        canvas.alpha_composite(fitted, dest=offset)
        return canvas

    @staticmethod
    def _meme_font_size(canvas_width: int) -> int:
        """Scale captions with the normalized output canvas, not source pixels."""

        return max(48, min(160, round(canvas_width * 0.065)))

    @staticmethod
    def _meme_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        return _caption_font(size)

    @staticmethod
    def _wrap_meme_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        return _wrap_caption_text(draw, text, font, max_width)

    @staticmethod
    def _positive_int(value: str | None, default: int) -> int:
        parsed = ImageProcessor._bounded_int(value, default, 1, 4_096)
        return parsed

    @staticmethod
    def _bounded_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError as error:
            raise InvalidRequest from error
        if parsed < minimum or parsed > maximum:
            raise InvalidRequest
        return parsed

    @staticmethod
    def _bounded_float(
        value: str | None,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        if value is None:
            return default
        try:
            parsed = float(value)
        except ValueError as error:
            raise InvalidRequest from error
        if parsed < minimum or parsed > maximum:
            raise InvalidRequest
        return parsed


class LocalQuoteCardProcessor:
    """Render reference-style quote cards without an AI call.

    The renderer deliberately accepts image bytes rather than Discord or storage
    objects.  The capability owns input selection and asset ingestion; this
    class owns only deterministic layout, typography, and composition.
    """

    async def render(
        self,
        request: QuoteCardRequest,
        image_data: bytes | None = None,
    ) -> bytes:
        return await asyncio.to_thread(self._run, request, image_data)

    @classmethod
    def _run(cls, request: QuoteCardRequest, image_data: bytes | None) -> bytes:
        normalized_quote = request.quote.strip()[:500]
        normalized_author = request.author.strip()[:120]
        if not normalized_quote:
            raise InvalidRequest

        size = (1_280, 720)
        canvas = Image.new("RGBA", size, "#000000")
        if image_data is not None and request.style.image_mode is not QuoteImageMode.HIDDEN:
            cls._compose_source(canvas, image_data, request)

        draw = ImageDraw.Draw(canvas)
        text_bounds = cls._text_bounds(request.style.image_mode, bool(image_data), size)
        quote_font, lines, line_height = cls._fit_quote_text(
            draw,
            normalized_quote,
            request.style.font,
            text_bounds[2] - text_bounds[0],
        )
        author_font = cls._quote_font(request.style.font, 30, italic=True)
        author_text = f"— {normalized_author}" if normalized_author else ""
        author_box = (
            draw.textbbox((0, 0), author_text, font=author_font)
            if author_text
            else (0, 0, 0, 0)
        )
        author_height = max(0, author_box[3] - author_box[1])
        quote_gap = 28 if author_text else 0
        author_gap = 18 if author_text else 0
        total_height = line_height * len(lines) + quote_gap + author_height + author_gap
        start_y = max(64, int((size[1] - total_height) // 2))

        for index, line in enumerate(lines):
            cls._draw_aligned(
                draw,
                line,
                quote_font,
                text_bounds,
                start_y + index * line_height,
                request.style.text_position,
                fill="#F8FAFC",
            )

        if author_text:
            cls._draw_aligned(
                draw,
                author_text,
                author_font,
                text_bounds,
                int(start_y + line_height * len(lines) + quote_gap),
                request.style.text_position,
                fill="#D1D5DB",
            )

        footer_font = cls._quote_font(QuoteFont.SANS, 16)
        footer = "Toolbox"
        footer_box = draw.textbbox((0, 0), footer, font=footer_font)
        draw.text(
            (size[0] - (footer_box[2] - footer_box[0]) - 34, size[1] - 30),
            footer,
            fill="#8B8B8B",
            font=footer_font,
        )

        output = io.BytesIO()
        canvas.save(output, format="PNG", compress_level=6)
        return output.getvalue()

    @classmethod
    def _compose_source(
        cls,
        canvas: Image.Image,
        image_data: bytes,
        request: QuoteCardRequest,
    ) -> None:
        try:
            with Image.open(io.BytesIO(image_data)) as source:
                source.load()
                if source.width * source.height > 20_000_000:
                    raise AssetRejected
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (AssetRejected, OSError, ValueError) as error:
            if isinstance(error, AssetRejected):
                raise
            raise AssetRejected from error

        if request.style.color_mode is QuoteColorMode.GRAYSCALE:
            image = ImageOps.grayscale(image).convert("RGB")

        width, height = canvas.size
        mode = request.style.image_mode
        if mode is QuoteImageMode.BACKGROUND:
            fitted = ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
            canvas.alpha_composite(fitted.convert("RGBA"))
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 155))
            canvas.alpha_composite(overlay)
            return

        image_width = width // 2
        fitted = ImageOps.fit(image, (image_width, height), method=Image.Resampling.LANCZOS)
        x_offset = 0 if mode is QuoteImageMode.LEFT else width - image_width
        canvas.alpha_composite(fitted.convert("RGBA"), dest=(x_offset, 0))

        # Fade the photo into the pure-black text field, matching the reference cards.
        gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gradient_draw = ImageDraw.Draw(gradient)
        fade_width = min(140, image_width // 3)
        if mode is QuoteImageMode.LEFT:
            fade_start = image_width - fade_width
            for x in range(fade_start, image_width):
                progress = (x - fade_start) / max(1, fade_width - 1)
                gradient_draw.line(
                    (x, 0, x, height),
                    fill=(0, 0, 0, round(progress * 255)),
                )
        else:
            image_start = width - image_width
            for x in range(image_start, image_start + fade_width):
                progress = (x - image_start) / max(1, fade_width - 1)
                gradient_draw.line(
                    (x, 0, x, height),
                    fill=(0, 0, 0, round((1 - progress) * 255)),
                )
        canvas.alpha_composite(gradient)

    @staticmethod
    def _text_bounds(
        mode: QuoteImageMode,
        has_image: bool,
        size: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        width, height = size
        margin = 70
        if not has_image or mode in {QuoteImageMode.BACKGROUND, QuoteImageMode.HIDDEN}:
            return (margin, 70, width - margin, height - 70)
        image_width = width // 2
        if mode is QuoteImageMode.LEFT:
            return (image_width + 24, 70, width - margin, height - 70)
        return (margin, 70, width - image_width - 24, height - 70)

    @classmethod
    def _fit_quote_text(
        cls,
        draw: ImageDraw.ImageDraw,
        quote: str,
        font_family: QuoteFont,
        max_width: int,
    ) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str], int]:
        for size in range(76, 35, -2):
            font = cls._quote_font(font_family, size)
            lines = _wrap_caption_text(draw, quote, font, max_width)[:7]
            line_height = size + max(10, round(size * 0.22))
            if len(lines) <= 5 or size <= 42:
                return font, lines, line_height
        font = cls._quote_font(font_family, 36)
        return font, _wrap_caption_text(draw, quote, font, max_width)[:7], 46

    @staticmethod
    def _draw_aligned(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        bounds: tuple[int, int, int, int],
        y: int,
        position: QuoteTextPosition,
        *,
        fill: str,
    ) -> None:
        left, _, right, _ = bounds
        box = draw.textbbox((0, 0), text, font=font)
        text_width = box[2] - box[0]
        if position is QuoteTextPosition.LEFT:
            x = left
        elif position is QuoteTextPosition.RIGHT:
            x = right - text_width
        else:
            x = left + (right - left - text_width) // 2
        draw.text((max(left, x), y), text, fill=fill, font=font)

    @staticmethod
    def _quote_font(
        family: QuoteFont,
        size: int,
        *,
        italic: bool = False,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        names = {
            QuoteFont.SANS: (
                "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf"
                if italic
                else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            ),
            QuoteFont.SERIF: (
                "/usr/share/fonts/truetype/noto/NotoSerif-Italic.ttf"
                if italic
                else "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
            ),
            QuoteFont.MONO: ("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",),
            QuoteFont.DISPLAY: ("/usr/share/fonts/truetype/noto/NotoSansDisplay-Regular.ttf",),
        }
        fallbacks = {
            QuoteFont.SANS: ("DejaVuSans-Oblique.ttf" if italic else "DejaVuSans.ttf",),
            QuoteFont.SERIF: ("DejaVuSerif-Italic.ttf" if italic else "DejaVuSerif.ttf",),
            QuoteFont.MONO: ("DejaVuSansMono.ttf",),
            QuoteFont.DISPLAY: ("DejaVuSansCondensed.ttf",),
        }
        for name in (*names[family], *fallbacks[family]):
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)


class LocalEmojiProcessor:
    """Render one emoji or custom-emoji image into a shareable square PNG."""

    async def render(
        self,
        request: EmojiRenderRequest,
        image_data: bytes | None = None,
    ) -> bytes:
        return await asyncio.to_thread(self._run, request, image_data)

    @classmethod
    def _run(
        cls,
        request: EmojiRenderRequest,
        image_data: bytes | None,
    ) -> bytes:
        size = max(128, min(request.size, 1_024))
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        if image_data:
            try:
                with Image.open(io.BytesIO(image_data)) as source:
                    source.seek(0)
                    source.load()
                    image = ImageOps.exif_transpose(source).convert("RGBA")
                    image.thumbnail(
                        (round(size * 0.86), round(size * 0.86)),
                        Image.Resampling.LANCZOS,
                    )
                    x = (size - image.width) // 2
                    y = (size - image.height) // 2
                    canvas.alpha_composite(image, dest=(x, y))
            except (EOFError, OSError, ValueError) as error:
                raise AssetRejected from error
        else:
            value = request.value.strip()[:100]
            if not value:
                raise InvalidRequest
            draw = ImageDraw.Draw(canvas)
            font = cls._emoji_font(value, size)
            box = draw.textbbox((0, 0), value, font=font, stroke_width=1)
            x = (size - (box[2] - box[0])) // 2 - box[0]
            y = (size - (box[3] - box[1])) // 2 - box[1]
            draw.text(
                (x, y),
                value,
                fill="#FFFFFF",
                font=font,
                stroke_width=max(1, size // 128),
                stroke_fill="#111827",
            )

        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _emoji_font(value: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        paths = (
            "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "DejaVuSans.ttf",
        )
        for font_size in range(round(size * 0.68), 30, -4):
            for path in paths:
                try:
                    font = ImageFont.truetype(path, size=font_size)
                except OSError:
                    continue
                # Prefer the largest font that keeps the whole value inside the card.
                probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
                box = probe.textbbox((0, 0), value, font=font, stroke_width=1)
                if box[2] - box[0] <= round(size * 0.82):
                    return font
        return ImageFont.load_default(size=max(24, round(size * 0.5)))
