from __future__ import annotations

from dataclasses import dataclass


VALID_ERROR_CODES = {
    "config_missing",
    "config_invalid",
    "busy",
    "kb_index_missing",
    "kb_index_stale",
    "kb_index_building",
    "kb_index_failed",
    "model_error",
    "llm_call_failed",
    "search_error",
    "tool_error",
    "schema_validation_failed",
    "runtime_error",
    "file_write_error",
    "task_not_found",
    "invalid_task_mode",
    "report_missing",
    "already_deposited",
}


@dataclass(frozen=True)
class ResearchError(Exception):
    code: str
    message: str

    def __post_init__(self) -> None:
        if self.code not in VALID_ERROR_CODES:
            raise ValueError(f"unknown error code: {self.code}")
        Exception.__init__(self, f"[{self.code}] {self.message}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}
