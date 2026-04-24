from __future__ import annotations

import os
import socket
from datetime import datetime

import docker
import psutil
from docker.errors import DockerException

from app.models.schemas import ContainerInfo, ContainerSummary, CpuUsage, MemoryUsage, ResourceMetrics


class LocalProbeService:
    """采集本机 CPU、内存和容器状态，供 Agent 推送到中心节点。"""

    def __init__(self) -> None:
        procfs_root = os.getenv("HBK_PROCFS_ROOT", "").strip()
        if procfs_root and hasattr(psutil, "PROCFS_PATH"):
            psutil.PROCFS_PATH = procfs_root

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
