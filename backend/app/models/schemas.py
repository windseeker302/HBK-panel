from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    percent: float = Field(ge=0, le=100, description="CPU 使用率")
    logical_cores: int = Field(ge=1, description="逻辑核心数")
    physical_cores: int | None = Field(default=None, description="物理核心数")


class MemoryUsage(BaseModel):
    total_bytes: int = Field(ge=0, description="总内存")
    used_bytes: int = Field(ge=0, description="已使用内存")
    available_bytes: int = Field(ge=0, description="可用内存")
    percent: float = Field(ge=0, le=100, description="内存使用率")


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
    request_id: str = Field(min_length=8, description="幂等请求 ID")
    node_name: str = Field(min_length=1, description="节点展示名称")
    address: str = Field(min_length=1, description="节点对外地址")
    node_sampled_at: datetime = Field(description="节点本地采样时间")
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
    idempotency_key: str = Field(min_length=8, description="任务幂等键")
    task_type: str = Field(min_length=1, description="任务类型")
    payload: dict[str, Any] = Field(default_factory=dict, description="任务参数")
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
        description="节点唯一标识，只允许字母、数字、-、_",
    )
    node_name: str = Field(min_length=1, max_length=64, description="节点展示名称")
    address_hint: str | None = Field(default=None, max_length=128, description="预期节点地址，可为空")
    install_path: str = Field(default="/opt/hbk-agent/HBK-Panel", min_length=1, max_length=256)


class AgentCommandBundle(BaseModel):
    bootstrap_script: str
    run_command: str
    systemd_unit: str
    systemd_enable_commands: str


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
