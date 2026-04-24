from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_authenticated_node_id, get_cluster_center_service
from app.models.schemas import (
    AgentHeartbeatRequest,
    AgentHeartbeatResponse,
    AgentTaskAckRequest,
    AgentTaskPullResponse,
    ClusterTaskResponse,
)
from app.services.monitoring import ClusterCenterService

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/heartbeat", response_model=AgentHeartbeatResponse, status_code=status.HTTP_202_ACCEPTED)
def push_heartbeat(
    payload: AgentHeartbeatRequest,
    node_id: str = Depends(get_authenticated_node_id),
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> AgentHeartbeatResponse:
    return service.register_heartbeat(node_id=node_id, payload=payload)


@router.get("/tasks/pull", response_model=AgentTaskPullResponse)
def pull_tasks(
    limit: int = 10,
    node_id: str = Depends(get_authenticated_node_id),
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> AgentTaskPullResponse:
    return service.pull_tasks(node_id=node_id, limit=limit)


@router.post("/tasks/{task_id}/ack", response_model=ClusterTaskResponse)
def ack_task(
    task_id: str,
    payload: AgentTaskAckRequest,
    node_id: str = Depends(get_authenticated_node_id),
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> ClusterTaskResponse:
    return service.ack_task(node_id=node_id, task_id=task_id, payload=payload)

