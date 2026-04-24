from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field


class ProbeInitiator(str, Enum):
    AGENT_SCHEDULER = "agent_scheduler"
    CENTER_TASK = "center_task"


class NodeStatus(str, Enum):
    ONLINE = "online"
    ABNORMAL = "abnormal"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RECEIVED = "received"
    DONE = "done"
    FAILED = "failed"


class NodeAction(str, Enum):
    CLEAR_STATE = "clear_state"
    DELETE = "delete"


class CpuUsage(BaseModel):
    percent: float = Field(ge=0, le=100, description="CPU usage percent")
    logical_cores: int = Field(ge=1, description="Logical CPU cores")
    physical_cores: int | None = Field(default=None, description="Physical CPU cores")


class MemoryUsage(BaseModel):
    total_bytes: int = Field(ge=0, description="Total memory bytes")
    used_bytes: int = Field(ge=0, description="Used memory bytes")
    available_bytes: int = Field(ge=0, description="Available memory bytes")
    percent: float = Field(ge=0, le=100, description="Memory usage percent")


class ResourceMetrics(BaseModel):
    cpu: CpuUsage
    memory: MemoryUsage


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str
    state: str
    health: str | None = None
    created_at: datetime | None = None


class ContainerSummary(BaseModel):
    total: int = 0
    running: int = 0
    exited: int = 0
    restarting: int = 0
    paused: int = 0
    dead: int = 0
    unknown: int = 0


class NodeRuntimeSnapshot(BaseModel):
    node_id: str
    node_name: str
    address: str
    status: NodeStatus
    server_received_at: datetime | None = None
    node_sampled_at: datetime | None = None
    probe_initiator: ProbeInitiator | None = None
    heartbeat_interval_seconds: int | None = None
    offline_after_seconds: int | None = None
    pending_tasks: int = 0


class NodeListItem(NodeRuntimeSnapshot):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    container_summary: ContainerSummary = Field(default_factory=ContainerSummary)
    container_runtime_available: bool = True


class NodeListResponse(BaseModel):
    items: list[NodeListItem]
    total: int
    online: int
    abnormal: int


class NodeOverviewResponse(NodeRuntimeSnapshot):
    container_summary: ContainerSummary = Field(default_factory=ContainerSummary)
    container_runtime_available: bool = True
    container_runtime_message: str | None = None


class NodeMetricsResponse(NodeRuntimeSnapshot):
    metrics: ResourceMetrics | None = None


class NodeContainersResponse(NodeRuntimeSnapshot):
    container_runtime_available: bool = True
    container_runtime_message: str | None = None
    summary: ContainerSummary = Field(default_factory=ContainerSummary)
    items: list[ContainerInfo] = Field(default_factory=list)


class AgentHeartbeatRequest(BaseModel):
    request_id: str = Field(min_length=8, description="Idempotent request ID")
    node_name: str = Field(min_length=1, description="Node display name")
    address: str = Field(min_length=1, description="Node public address")
    node_sampled_at: datetime = Field(description="Node sampled time")
    heartbeat_interval_seconds: int = Field(default=12, ge=10, le=15)
    offline_after_seconds: int = Field(default=35, ge=30, le=45)
    probe_initiator: ProbeInitiator = Field(default=ProbeInitiator.AGENT_SCHEDULER)
    metrics: ResourceMetrics
    container_runtime_available: bool = True
    container_runtime_message: str | None = None
    containers: list[ContainerInfo] = Field(default_factory=list)


class AgentHeartbeatResponse(BaseModel):
    accepted: bool
    duplicated: bool
    node_id: str
    request_id: str
    server_received_at: datetime
    next_heartbeat_after_seconds: int
    pending_tasks: int


class CenterTaskCreateRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, description="Task idempotency key")
    task_type: str = Field(min_length=1, description="Task type")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task payload")
    timeout_seconds: int = Field(default=15, ge=1, le=120)


class AgentTaskAckRequest(BaseModel):
    status: TaskStatus
    result: dict[str, Any] = Field(default_factory=dict)


class ClusterTaskResponse(BaseModel):
    task_id: str
    node_id: str
    task_type: str
    payload: dict[str, Any]
    timeout_seconds: int
    status: TaskStatus
    created_at: datetime
    acked_at: datetime | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class AgentTaskPullResponse(BaseModel):
    node_id: str
    server_time: datetime
    items: list[ClusterTaskResponse]


class NodeRegistrationRequest(BaseModel):
    node_id: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Node unique identifier",
    )
    node_name: str = Field(min_length=1, max_length=64, description="Node display name")
    address_hint: str | None = Field(default=None, max_length=128, description="Expected node address")
    install_path: str = Field(default="/opt/hbk-agent/HBK-Panel", min_length=1, max_length=256)
    center_url: AnyHttpUrl | None = Field(default=None, description="Agent public center URL override")


class AgentCommandBundle(BaseModel):
    github_clone_commands: str
    bootstrap_script: str
    run_command: str
    systemd_unit: str
    systemd_enable_commands: str
    docker_build_command: str
    docker_compose_up_command: str


class NodeRegistrationResponse(BaseModel):
    node_id: str
    node_name: str
    token: str
    address_hint: str | None = None
    created_at: datetime
    center_url: str
    commands: AgentCommandBundle


class NodeActionResponse(BaseModel):
    node_id: str
    action: NodeAction
    message: str
    server_time: datetime
    registered: bool
    runtime_state_cleared: bool
    pending_tasks: int = 0
