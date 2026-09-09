from __future__ import annotations

from dataclasses import dataclass, FrozenInstanceError


VALID_ERROR_CODES = {
    "config_missing",
    "config_invalid",
    "busy",
    "kb_index_missing",
    "kb_index_stale",
    "kb_index_building",
    "kb_index_failed",
    "kb_rebuild_error",
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


def _research_error_setattr(self: ResearchError, name: str, value: object) -> None:
    # Exception machinery sets dunders at the Python level (contextlib's
    # __exit__ assigns __traceback__ on Python 3.12). The generated frozen
    # __setattr__ rejects that and masks the real error with
    # FrozenInstanceError, so allow dunder assignment while keeping the
    # code/message fields frozen. (Defined post-class: @dataclass(frozen=True)
    # refuses to overwrite a __setattr__ present in the class body.)
    if name.startswith("__"):
        object.__setattr__(self, name, value)
        return
    raise FrozenInstanceError(f"cannot assign to field '{name}'")


ResearchError.__setattr__ = _research_error_setattr  # type: ignore[method-assign]
