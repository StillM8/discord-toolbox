"""Meaningful application errors used to normalize provider and storage failures."""

from __future__ import annotations


class ToolboxError(Exception):
    """Base error with safe user-facing metadata."""

    code = "toolbox_error"
    user_message = "Toolbox could not complete that request."
    retryable = False


class InvalidRequest(ToolboxError):
    code = "invalid_request"
    user_message = "That request is not valid."


class PermissionDenied(ToolboxError):
    code = "permission_denied"
    user_message = "You are not allowed to perform that action."


class FeatureDisabled(ToolboxError):
    code = "feature_disabled"
    user_message = "That Toolbox feature is currently disabled."


class ProviderUnavailable(ToolboxError):
    code = "provider_unavailable"
    user_message = "That external service is temporarily unavailable."
    retryable = True


class ProviderTimeout(ProviderUnavailable):
    code = "provider_timeout"
    user_message = "That external service took too long to respond."


class RateLimited(ToolboxError):
    code = "rate_limited"
    user_message = "Toolbox is rate-limited for that operation. Try again shortly."
    retryable = True


class AssetRejected(ToolboxError):
    code = "asset_rejected"
    user_message = "That file cannot be processed safely."


class SessionExpired(ToolboxError):
    code = "session_expired"
    user_message = "That Toolbox interaction has expired."
