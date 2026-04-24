from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import docker
import psutil
from docker.errors import DockerException
from fastapi import HTTPException, status

from app.models.schemas import (
    AgentCommandBundle,
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentTaskAckRequest,
    AgentTaskPullResponse,
    CenterTaskCreateRequest,
    ClusterTaskResponse,
    ContainerInfo,
    ContainerSummary,
    CpuUsage,
    MemoryUsage,
    NodeAction,
    NodeActionResponse,
    NodeContainersResponse,
    NodeListItem,
    NodeListResponse,
    NodeMetricsResponse,
    NodeOverviewResponse,
    NodeRegistrationRequest,
    NodeRegistrationResponse,
    NodeStatus,
    ProbeInitiator,
    ResourceMetrics,
    TaskStatus,
)

DEFAULT_NODE_TOKENS = {
    "node-a": "token-node-a-demo",
    "node-b": "token-node-b-demo",
    "node-c": "token-node-c-demo",
}


def load_node_tokens() -> dict[str, str]:
    raw = os.getenv("HBK_NODE_TOKENS_JSON")
    if not raw:
        return DEFAULT_NODE_TOKENS.copy()

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("HBK_NODE_TOKENS_JSON 必须是 JSON 对象")
    return {str(key): str(value) for key, value in parsed.items()}


@dataclass
class RegisteredNode:
    node_id: str
    node_name: str
    token: str
    created_at: datetime
    address_hint: str | None = None
    source: str = "runtime"


@dataclass
class NodeRecord:
    node_id: str
    node_name: str
    address: str
    request_id: str
    server_received_at: datetime
    node_sampled_at: datetime
    heartbeat_interval_seconds: int
    offline_after_seconds: int
    probe_initiator: ProbeInitiator
    metrics: ResourceMetrics
    containers: list[ContainerInfo] = field(default_factory=list)
    container_summary: ContainerSummary = field(default_factory=ContainerSummary)
    container_runtime_available: bool = True
    container_runtime_message: str | None = None


@dataclass
class TaskRecord:
    task_id: str
    node_id: str
    task_type: str
    payload: dict
    timeout_seconds: int
    idempotency_key: str
    status: TaskStatus
    created_at: datetime
    acked_at: datetime | None = None
    result: dict = field(default_factory=dict)

    def to_response(self) -> ClusterTaskResponse:
        return ClusterTaskResponse(
            task_id=self.task_id,
            node_id=self.node_id,
            task_type=self.task_type,
            payload=self.payload,
            timeout_seconds=self.timeout_seconds,
            status=self.status,
            created_at=self.created_at,
            acked_at=self.acked_at,
            result=self.result,
        )


class LocalProbeService:
    """采集本机 CPU、内存和容器状态，供 Agent 推送到中心节点。"""

    def collect_snapshot(self) -> tuple[ResourceMetrics, bool, str | None, list[ContainerInfo]]:
        metrics = self.collect_metrics()
        container_available, container_message, containers = self.collect_containers()
        return metrics, container_available, container_message, containers

    def collect_metrics(self) -> ResourceMetrics:
        memory = psutil.virtual_memory()
        return ResourceMetrics(
            cpu=CpuUsage(
                percent=round(psutil.cpu_percent(interval=0.2), 2),
                logical_cores=psutil.cpu_count() or 1,
                physical_cores=psutil.cpu_count(logical=False),
            ),
            memory=MemoryUsage(
                total_bytes=memory.total,
                used_bytes=memory.used,
                available_bytes=memory.available,
                percent=round(memory.percent, 2),
            ),
        )

    def collect_containers(self) -> tuple[bool, str | None, list[ContainerInfo]]:
        client = None
        try:
            client = docker.from_env()
            containers = client.containers.list(all=True)
        except (DockerException, FileNotFoundError, OSError) as exc:
            return False, self.describe_docker_exception(exc), []

        items: list[ContainerInfo] = []
        for container in containers:
            attrs = container.attrs or {}
            state_info = attrs.get("State", {})
            health = None
            health_info = state_info.get("Health")
            if isinstance(health_info, dict):
                health = health_info.get("Status")

            created_at = None
            created_raw = attrs.get("Created")
            if isinstance(created_raw, str):
                created_at = self._parse_docker_datetime(created_raw)

            image_tags = getattr(container.image, "tags", None) or []
            image_name = image_tags[0] if image_tags else attrs.get("Config", {}).get("Image", "unknown")
            items.append(
                ContainerInfo(
                    id=container.short_id,
                    name=container.name,
                    image=image_name,
                    status=container.status or "unknown",
                    state=container.status or state_info.get("Status") or "unknown",
                    health=health,
                    created_at=created_at,
                )
            )

        if client is not None:
            client.close()

        return True, None if items else "当前节点没有容器", items

    @staticmethod
    def resolve_primary_address() -> str:
        for interfaces in psutil.net_if_addrs().values():
            for address in interfaces:
                if address.family != socket.AF_INET:
                    continue
                if address.address.startswith("127.") or address.address.startswith("169.254."):
                    continue
                return address.address
        return "127.0.0.1"

    @staticmethod
    def describe_docker_exception(exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if "createfile" in lowered or "system cannot find the file specified" in lowered:
            return "未检测到 Docker Engine，请确认 Docker Desktop 已安装并已启动。"
        if "connection aborted" in lowered or "actively refused" in lowered:
            return "Docker Engine 未响应，请确认服务正在运行。"
        return message

    @staticmethod
    def build_container_summary(containers: list[ContainerInfo]) -> ContainerSummary:
        summary = ContainerSummary(total=len(containers))
        mapping = {
            "running": "running",
            "exited": "exited",
            "restarting": "restarting",
            "paused": "paused",
            "dead": "dead",
        }
        for container in containers:
            bucket = mapping.get(container.state, "unknown")
            setattr(summary, bucket, getattr(summary, bucket) + 1)
        return summary

    @staticmethod
    def _parse_docker_datetime(value: str) -> datetime | None:
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None


class ClusterCenterService:
    """中心节点：接收 Agent 心跳、管理节点注册并支持任务下发。"""

    def __init__(self) -> None:
        self.require_tls = os.getenv("HBK_REQUIRE_TLS", "false").lower() == "true"
        now = datetime.now(UTC)
        self._registered_nodes: dict[str, RegisteredNode] = {
            node_id: RegisteredNode(
                node_id=node_id,
                node_name=node_id,
                token=token,
                created_at=now,
                address_hint=None,
                source="bootstrap",
            )
            for node_id, token in load_node_tokens().items()
        }
        self._nodes: dict[str, NodeRecord] = {}
        self._request_index: dict[tuple[str, str], datetime] = {}
        self._tasks: dict[str, list[TaskRecord]] = {node_id: [] for node_id in self._registered_nodes}
        self._task_idempotency: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def authenticate_node(self, node_id: str, token: str, scheme: str) -> bool:
        registered = self._registered_nodes.get(node_id)
        if registered is None:
            return False
        if registered.token != token:
            return False
        if self.require_tls and scheme != "https":
            return False
        return True

    def register_node(self, payload: NodeRegistrationRequest, center_url: str) -> NodeRegistrationResponse:
        with self._lock:
            if payload.node_id in self._registered_nodes:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"节点 {payload.node_id} 已存在，请直接部署 Agent 或后续实现 token 轮换。",
                )

            registered = RegisteredNode(
                node_id=payload.node_id,
                node_name=payload.node_name,
                token=self._generate_token(),
                created_at=datetime.now(UTC),
                address_hint=payload.address_hint,
                source="runtime",
            )
            self._registered_nodes[registered.node_id] = registered
            self._tasks[registered.node_id] = []

        commands = self._build_command_bundle(
            center_url=center_url.rstrip("/"),
            install_path=payload.install_path.rstrip("/"),
            node=registered,
        )
        return NodeRegistrationResponse(
            node_id=registered.node_id,
            node_name=registered.node_name,
            token=registered.token,
            address_hint=registered.address_hint,
            created_at=registered.created_at,
            center_url=center_url.rstrip("/"),
            commands=commands,
        )

    def register_heartbeat(self, node_id: str, payload: AgentHeartbeatRequest) -> AgentHeartbeatResponse:
        now = datetime.now(UTC)
        request_key = (node_id, payload.request_id)

        with self._lock:
            self._prune_request_index(now)
            if request_key in self._request_index:
                return AgentHeartbeatResponse(
                    accepted=True,
                    duplicated=True,
                    node_id=node_id,
                    request_id=payload.request_id,
                    server_received_at=self._request_index[request_key],
                    next_heartbeat_after_seconds=payload.heartbeat_interval_seconds,
                    pending_tasks=self._pending_task_count(node_id),
                )

            self._request_index[request_key] = now
            containers = list(payload.containers)
            summary = LocalProbeService.build_container_summary(containers)
            self._nodes[node_id] = NodeRecord(
                node_id=node_id,
                node_name=payload.node_name,
                address=payload.address,
                request_id=payload.request_id,
                server_received_at=now,
                node_sampled_at=payload.node_sampled_at,
                heartbeat_interval_seconds=payload.heartbeat_interval_seconds,
                offline_after_seconds=payload.offline_after_seconds,
                probe_initiator=payload.probe_initiator,
                metrics=payload.metrics,
                containers=containers,
                container_summary=summary,
                container_runtime_available=payload.container_runtime_available,
                container_runtime_message=payload.container_runtime_message,
            )

            return AgentHeartbeatResponse(
                accepted=True,
                duplicated=False,
                node_id=node_id,
                request_id=payload.request_id,
                server_received_at=now,
                next_heartbeat_after_seconds=payload.heartbeat_interval_seconds,
                pending_tasks=self._pending_task_count(node_id),
            )

    def list_nodes(self) -> NodeListResponse:
        with self._lock:
            items = [self._build_list_item(node_id) for node_id in self._registered_nodes]

        online = sum(1 for item in items if item.status == NodeStatus.ONLINE)
        abnormal = len(items) - online
        return NodeListResponse(items=items, total=len(items), online=online, abnormal=abnormal)

    def get_node_overview(self, node_id: str) -> NodeOverviewResponse:
        self._ensure_known_node(node_id)
        with self._lock:
            record = self._nodes.get(node_id)
            pending_tasks = self._pending_task_count(node_id)
        return self._build_overview(node_id=node_id, record=record, pending_tasks=pending_tasks)

    def get_node_metrics(self, node_id: str) -> NodeMetricsResponse:
        self._ensure_known_node(node_id)
        with self._lock:
            record = self._nodes.get(node_id)
            pending_tasks = self._pending_task_count(node_id)
        snapshot = self._build_runtime_snapshot(node_id=node_id, record=record, pending_tasks=pending_tasks)
        return NodeMetricsResponse(**snapshot, metrics=record.metrics if record else None)

    def get_node_containers(self, node_id: str) -> NodeContainersResponse:
        self._ensure_known_node(node_id)
        with self._lock:
            record = self._nodes.get(node_id)
            pending_tasks = self._pending_task_count(node_id)

        snapshot = self._build_runtime_snapshot(node_id=node_id, record=record, pending_tasks=pending_tasks)
        return NodeContainersResponse(
            **snapshot,
            container_runtime_available=record.container_runtime_available if record else True,
            container_runtime_message=record.container_runtime_message if record else "节点尚未上报容器信息",
            summary=record.container_summary if record else ContainerSummary(),
            items=record.containers if record else [],
        )

    def create_task(self, node_id: str, payload: CenterTaskCreateRequest) -> ClusterTaskResponse:
        self._ensure_known_node(node_id)
        key = (node_id, payload.idempotency_key)

        with self._lock:
            existing_task_id = self._task_idempotency.get(key)
            if existing_task_id:
                task = self._find_task(node_id=node_id, task_id=existing_task_id)
                return task.to_response()

            task = TaskRecord(
                task_id=str(uuid.uuid4()),
                node_id=node_id,
                task_type=payload.task_type,
                payload=payload.payload,
                timeout_seconds=payload.timeout_seconds,
                idempotency_key=payload.idempotency_key,
                status=TaskStatus.PENDING,
                created_at=datetime.now(UTC),
            )
            self._tasks.setdefault(node_id, []).append(task)
            self._task_idempotency[key] = task.task_id
            return task.to_response()

    def pull_tasks(self, node_id: str, limit: int = 10) -> AgentTaskPullResponse:
        self._ensure_known_node(node_id)
        limit = max(1, min(limit, 50))
        with self._lock:
            pending = [
                task.to_response()
                for task in self._tasks.get(node_id, [])
                if task.status == TaskStatus.PENDING
            ][:limit]
        return AgentTaskPullResponse(node_id=node_id, server_time=datetime.now(UTC), items=pending)

    def ack_task(self, node_id: str, task_id: str, payload: AgentTaskAckRequest) -> ClusterTaskResponse:
        self._ensure_known_node(node_id)
        with self._lock:
            task = self._find_task(node_id=node_id, task_id=task_id)
            task.status = payload.status
            task.result = payload.result
            task.acked_at = datetime.now(UTC)
            return task.to_response()

    def clear_node_state(self, node_id: str) -> NodeActionResponse:
        self._ensure_known_node(node_id)
        with self._lock:
            runtime_state_cleared = self._nodes.pop(node_id, None) is not None
            self._remove_request_index(node_id)
            pending_tasks = self._pending_task_count(node_id)

        message = "已清理节点运行态缓存，注册信息和 token 保留，下一次心跳会重新出现。"
        if not runtime_state_cleared:
            message = "节点当前没有运行态缓存，仅保留注册信息不变。"

        return NodeActionResponse(
            node_id=node_id,
            action=NodeAction.CLEAR_STATE,
            message=message,
            server_time=datetime.now(UTC),
            registered=True,
            runtime_state_cleared=runtime_state_cleared,
            pending_tasks=pending_tasks,
        )

    def delete_node(self, node_id: str) -> NodeActionResponse:
        self._ensure_known_node(node_id)
        with self._lock:
            registered = self._registered_nodes.pop(node_id)
            runtime_state_cleared = self._nodes.pop(node_id, None) is not None
            self._remove_request_index(node_id)
            self._tasks.pop(node_id, None)
            self._remove_task_idempotency(node_id)

        message = "节点已从中心注册表移除，token 已失效，后续 Agent 心跳将返回 401。"
        if registered.source == "bootstrap":
            message += " 但如果中心重启且启动配置仍包含该节点，它会重新出现。"

        return NodeActionResponse(
            node_id=node_id,
            action=NodeAction.DELETE,
            message=message,
            server_time=datetime.now(UTC),
            registered=False,
            runtime_state_cleared=runtime_state_cleared,
            pending_tasks=0,
        )

    def _build_list_item(self, node_id: str) -> NodeListItem:
        record = self._nodes.get(node_id)
        snapshot = self._build_runtime_snapshot(
            node_id=node_id,
            record=record,
            pending_tasks=self._pending_task_count(node_id),
        )
        return NodeListItem(
            **snapshot,
            cpu_percent=record.metrics.cpu.percent if record else None,
            memory_percent=record.metrics.memory.percent if record else None,
            container_summary=record.container_summary if record else ContainerSummary(),
            container_runtime_available=record.container_runtime_available if record else True,
        )

    def _build_overview(
        self,
        node_id: str,
        record: NodeRecord | None,
        pending_tasks: int,
    ) -> NodeOverviewResponse:
        snapshot = self._build_runtime_snapshot(node_id=node_id, record=record, pending_tasks=pending_tasks)
        return NodeOverviewResponse(
            **snapshot,
            container_summary=record.container_summary if record else ContainerSummary(),
            container_runtime_available=record.container_runtime_available if record else True,
            container_runtime_message=record.container_runtime_message if record else "节点尚未开始上报数据",
        )

    def _build_runtime_snapshot(
        self,
        node_id: str,
        record: NodeRecord | None,
        pending_tasks: int,
    ) -> dict:
        registered = self._registered_nodes[node_id]
        if record is None:
            return {
                "node_id": node_id,
                "node_name": registered.node_name,
                "address": registered.address_hint or "-",
                "status": NodeStatus.ABNORMAL,
                "server_received_at": None,
                "node_sampled_at": None,
                "probe_initiator": None,
                "heartbeat_interval_seconds": None,
                "offline_after_seconds": None,
                "pending_tasks": pending_tasks,
            }

        return {
            "node_id": record.node_id,
            "node_name": record.node_name,
            "address": record.address,
            "status": self._resolve_status(record),
            "server_received_at": record.server_received_at,
            "node_sampled_at": record.node_sampled_at,
            "probe_initiator": record.probe_initiator,
            "heartbeat_interval_seconds": record.heartbeat_interval_seconds,
            "offline_after_seconds": record.offline_after_seconds,
            "pending_tasks": pending_tasks,
        }

    @staticmethod
    def _resolve_status(record: NodeRecord) -> NodeStatus:
        now = datetime.now(UTC)
        delta = now - record.server_received_at
        return NodeStatus.ONLINE if delta.total_seconds() <= record.offline_after_seconds else NodeStatus.ABNORMAL

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(24)

    def _build_command_bundle(
        self,
        center_url: str,
        install_path: str,
        node: RegisteredNode,
    ) -> AgentCommandBundle:
        backend_path = f"{install_path}/backend"
        service_name = f"hbk-agent-{node.node_id}"
        escaped_name = node.node_name.replace('"', '\\"')
        address_expression = '${HBK_NODE_ADDRESS:-$(hostname -I | awk \'{print $1}\')}'

        bootstrap_script = "\n".join(
            [
                "sudo dnf install -y python3.11 git",
                f"mkdir -p {install_path}",
                f"cd {backend_path}",
                "python3.11 -m venv .venv",
                "source .venv/bin/activate",
                "pip install -r requirements.txt",
            ]
        )

        run_command = (
            "./.venv/bin/python scripts/demo_agent.py "
            f'--center-url "{center_url}" '
            f'--node-id "{node.node_id}" '
            f'--token "{node.token}" '
            f'--node-name "{escaped_name}" '
            f'--address "{address_expression}" '
            "--interval 12 "
            "--offline-after 35 "
            "--auto-ack"
        )

        systemd_unit = "\n".join(
            [
                "[Unit]",
                f"Description=HBK Agent ({node.node_id})",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={backend_path}",
                (
                    f"ExecStart={backend_path}/.venv/bin/python scripts/demo_agent.py "
                    f'--center-url "{center_url}" '
                    f'--node-id "{node.node_id}" '
                    f'--token "{node.token}" '
                    f'--node-name "{escaped_name}" '
                    f'--address "{address_expression}" '
                    "--interval 12 --offline-after 35 --auto-ack"
                ),
                "Restart=always",
                "RestartSec=5",
                "Environment=PYTHONUNBUFFERED=1",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
            ]
        )

        systemd_enable_commands = "\n".join(
            [
                f"sudo tee /etc/systemd/system/{service_name}.service > /dev/null <<'EOF'",
                systemd_unit,
                "EOF",
                "sudo systemctl daemon-reload",
                f"sudo systemctl enable --now {service_name}",
                f"sudo systemctl status {service_name}",
            ]
        )

        return AgentCommandBundle(
            bootstrap_script=bootstrap_script,
            run_command=run_command,
            systemd_unit=systemd_unit,
            systemd_enable_commands=systemd_enable_commands,
        )

    def _pending_task_count(self, node_id: str) -> int:
        return sum(1 for task in self._tasks.get(node_id, []) if task.status == TaskStatus.PENDING)

    def _find_task(self, node_id: str, task_id: str) -> TaskRecord:
        for task in self._tasks.get(node_id, []):
            if task.task_id == task_id:
                return task
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"任务 {task_id} 不存在")

    def _ensure_known_node(self, node_id: str) -> None:
        if node_id not in self._registered_nodes:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"节点 {node_id} 未注册")

    def _prune_request_index(self, now: datetime) -> None:
        ttl = timedelta(minutes=15)
        expired = [key for key, value in self._request_index.items() if now - value > ttl]
        for key in expired:
            self._request_index.pop(key, None)

    def _remove_request_index(self, node_id: str) -> None:
        expired_keys = [key for key in self._request_index if key[0] == node_id]
        for key in expired_keys:
            self._request_index.pop(key, None)

    def _remove_task_idempotency(self, node_id: str) -> None:
        expired_keys = [key for key in self._task_idempotency if key[0] == node_id]
        for key in expired_keys:
            self._task_idempotency.pop(key, None)
