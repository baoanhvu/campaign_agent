"""Error tree — 40 error codes organized by layer.

Never raise bare Exception. Always use a typed error from this tree so the
API layer can map to the correct HTTP status and SSE error event.
"""
from __future__ import annotations


class AgentError(Exception):
    code: str = "AGENT_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", *, details: dict | None = None):
        super().__init__(message or self.code)
        self.details = details or {}


class RetryableError(AgentError):
    code = "RETRYABLE"
    http_status = 503


class RoutingError(AgentError):
    code = "ROUTING_ERROR"
    http_status = 400


class OutOfScopeError(AgentError):
    code = "OUT_OF_SCOPE"
    http_status = 200


class PlanningError(AgentError):
    code = "PLANNING_ERROR"
    http_status = 500


class SemanticCompileError(AgentError):
    code = "SEMANTIC_COMPILE_ERROR"
    http_status = 500


class UnknownMetricError(SemanticCompileError):
    code = "UNKNOWN_METRIC"


class DatabaseError(RetryableError):
    code = "DATABASE_ERROR"


class DatabasePoolError(DatabaseError):
    code = "DATABASE_POOL_ERROR"


class LLMError(RetryableError):
    code = "LLM_ERROR"


class LLMRateLimitError(LLMError):
    code = "LLM_RATE_LIMIT"
    http_status = 429


class LLMUnavailableError(LLMError):
    code = "LLM_UNAVAILABLE"


class NumericGroundingError(AgentError):
    code = "NUMERIC_GROUNDING_FAILED"


class EntityGroundingError(AgentError):
    code = "ENTITY_GROUNDING_FAILED"


class StatsGuardError(AgentError):
    code = "STATS_GUARD_FAILED"


class InsufficientSampleError(StatsGuardError):
    code = "INSUFFICIENT_SAMPLE"


class SkewWarning(StatsGuardError):
    code = "SKEW_DETECTED"


class TrustBlockedError(AgentError):
    code = "TRUST_BLOCKED"
    http_status = 200


class JudgeError(AgentError):
    code = "JUDGE_ERROR"


class IdentityError(AgentError):
    code = "IDENTITY_ERROR"


class GatewayError(AgentError):
    code = "GATEWAY_ERROR"


class PolicyDeniedError(GatewayError):
    code = "POLICY_DENIED"
    http_status = 403


class DataQualityError(AgentError):
    code = "DATA_QUALITY"


class DQBlockError(DataQualityError):
    code = "DQ_BLOCK"


class CacheError(AgentError):
    code = "CACHE_ERROR"


class ConfigError(AgentError):
    code = "CONFIG_ERROR"


class PromptError(AgentError):
    code = "PROMPT_ERROR"


class RenderError(AgentError):
    code = "RENDER_ERROR"


class StreamingError(AgentError):
    code = "STREAMING_ERROR"


class ETLError(AgentError):
    code = "ETL_ERROR"


class AdminAuthError(AgentError):
    code = "ADMIN_AUTH"
    http_status = 401


class NotFoundError(AgentError):
    code = "NOT_FOUND"
    http_status = 404


class ValidationError(AgentError):
    code = "VALIDATION"
    http_status = 422


class UnsupportedQueryError(AgentError):
    code = "UNSUPPORTED_QUERY"
    http_status = 200


class DegradedModeError(AgentError):
    code = "DEGRADED_MODE"
    http_status = 200
