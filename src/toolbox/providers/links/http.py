"""Bounded HTML/text link fetcher with no redirects or provider-specific leakage."""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from typing import Any, cast

import httpx
import trafilatura  # pyright: ignore[reportMissingTypeStubs]
from selectolax.parser import (
    HTMLParser as SelectolaxHTMLParser,  # pyright: ignore[reportMissingTypeStubs]
)

from toolbox.core.contracts import LinkFetcher
from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable
from toolbox.core.models import LinkDocument
from toolbox.infrastructure.url_policy import RemoteUrlPolicy


class _TextParser(HTMLParser):
    def __init__(self, max_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self._max_chars = max_chars
        self.title: str | None = None
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif normalized == "title" and self._skip_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif normalized == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self._title_parts.append(cleaned)
        if sum(len(part) for part in self._text_parts) < self._max_chars:
            self._text_parts.append(cleaned)

    def document(self, url: str) -> LinkDocument:
        title = " ".join(self._title_parts).strip() or None
        text = " ".join(self._text_parts).strip()[: self._max_chars]
        return LinkDocument(url=url, title=title, text=text)


class HttpLinkFetcher(LinkFetcher):
    """Fetch only bounded text documents through the managed HTTP client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_bytes: int = 2_000_000,
        max_chars: int = 40_000,
        url_policy: RemoteUrlPolicy | None = None,
    ) -> None:
        self._client = client
        self._max_bytes = max_bytes
        self._max_chars = max_chars
        self._url_policy = url_policy or RemoteUrlPolicy()

    async def fetch(self, url: str) -> LinkDocument:
        await self._url_policy.validate_network_target(url)
        if len(url) > 2_000:
            raise InvalidRequest
        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code >= 400 or response.is_redirect:
                    raise ProviderUnavailable
                content_type = response.headers.get("content-type", "").lower()
                if not (
                    content_type.startswith("text/")
                    or "html" in content_type
                    or "json" in content_type
                ):
                    raise InvalidRequest
                declared = response.headers.get("content-length")
                if declared is not None and int(declared) > self._max_bytes:
                    raise InvalidRequest
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self._max_bytes:
                        raise InvalidRequest
                    chunks.append(chunk)
            raw = b"".join(chunks)
        except (InvalidRequest, ProviderUnavailable):
            raise
        except ValueError as error:
            raise InvalidRequest from error
        except httpx.TimeoutException as error:
            raise ProviderTimeout from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable from error
        document = await asyncio.to_thread(self._extract, raw, url)
        if not document.text:
            raise ProviderUnavailable
        return document

    def _extract(self, raw: bytes, url: str) -> LinkDocument:
        """Extract article text with bounded parser fallbacks."""

        text = raw.decode("utf-8", errors="replace")
        extracted: str | None = None
        title: object | None = None
        try:
            extracted = trafilatura.extract(
                text,
                url=url,
                include_comments=False,
                include_links=False,
                favor_precision=True,
                output_format="txt",
            )
            metadata = trafilatura.extract_metadata(text, default_url=url)
            title = getattr(metadata, "title", None)
        except (AttributeError, KeyError, TypeError, ValueError):
            # Malformed HTML should still get the bounded parser fallbacks.
            pass
        if isinstance(extracted, str) and extracted.strip():
            return LinkDocument(
                url=url,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                text=extracted.strip()[: self._max_chars],
            )

        try:
            tree = cast(Any, SelectolaxHTMLParser(text))
            for node in tree.css("script,style,noscript,svg"):
                node.decompose()
            body = tree.body
            fallback_text = body.text(separator=" ") if body is not None else tree.text()
            fallback_title = tree.css_first("title")
            if fallback_title is not None and not title:
                title = fallback_title.text(strip=True)
            return LinkDocument(
                url=url,
                title=title.strip() if isinstance(title, str) and title.strip() else None,
                text=" ".join(str(fallback_text).split())[: self._max_chars],
            )
        except (AttributeError, TypeError, ValueError):
            parser = _TextParser(self._max_chars)
            parser.feed(text)
            return parser.document(url)
