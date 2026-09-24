"""Нормализованные модели агрегатора и общие типы."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SystemType(str, Enum):
    DSH = "dsh"
    OPENCODE = "opencode"


class AgentStatus(str, Enum):
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Tokens(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0


class AgentState(BaseModel):
    """Нормализованное состояние агента/субагента."""

    id: str
    system: SystemType
    parent_id: Optional[str] = None
    title: str = ""
    project: Optional[str] = None
    status: AgentStatus = AgentStatus.UNKNOWN
    last_step: Optional[str] = None
    tokens: Optional[Tokens] = None
    cost: Optional[float] = None
    started_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class EventType(str, Enum):
    STATE_UPDATE = "state_update"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_WAITING = "agent_waiting"
    SNAPSHOT = "snapshot"
    SYSTEM_OFFLINE = "system_offline"
    SYSTEM_ONLINE = "system_online"


class AggregatorEvent(BaseModel):
    type: EventType
    agent: Optional[AgentState] = None
    agents: Optional[list[AgentState]] = None
    system: Optional[SystemType] = None
    message: Optional[str] = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuthRequest(BaseModel):
    init_data: str = Field(..., alias="initData")


class AuthResponse(BaseModel):
    ok: bool
    message: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str = "3.6.0"
    dsh: str
    opencode: str
    token_configured: bool
    kill_switch: bool
    public_url: str = ""
    secret_path: str = ""
    network_mode: str = "hybrid"
    lan_urls: list[str] = []
    network_hint: str = ""
