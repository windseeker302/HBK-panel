from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import get_cluster_center_service
from app.models.schemas import (
    CenterTaskCreateRequest,
    ClusterTaskResponse,
    NodeActionResponse,
    NodeContainersResponse,
    NodeListResponse,
    NodeMetricsResponse,
    NodeOverviewResponse,
    NodeRegistrationRequest,
    NodeRegistrationResponse,
)
from app.services.monitoring import ClusterCenterService

router = APIRouter(prefix="/api/center", tags=["center"])


@router.post("/nodes/register", response_model=NodeRegistrationResponse, status_code=status.HTTP_201_CREATED)
def register_node(
    payload: NodeRegistrationRequest,
    request: Request,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> NodeRegistrationResponse:
    return service.register_node(payload=payload, center_url=str(request.base_url))


@router.get("/nodes", response_model=NodeListResponse)
def get_nodes(service: ClusterCenterService = Depends(get_cluster_center_service)) -> NodeListResponse:
    return service.list_nodes()


@router.get("/nodes/{node_id}", response_model=NodeOverviewResponse)
def get_node_overview(
    node_id: str,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> NodeOverviewResponse:
    return service.get_node_overview(node_id)


@router.get("/nodes/{node_id}/metrics", response_model=NodeMetricsResponse)
def get_node_metrics(
    node_id: str,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> NodeMetricsResponse:
    return service.get_node_metrics(node_id)


@router.get("/nodes/{node_id}/containers", response_model=NodeContainersResponse)
def get_node_containers(
    node_id: str,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> NodeContainersResponse:
    return service.get_node_containers(node_id)


@router.post("/nodes/{node_id}/tasks", response_model=ClusterTaskResponse)
def create_node_task(
    node_id: str,
    payload: CenterTaskCreateRequest,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> ClusterTaskResponse:
    return service.create_task(node_id=node_id, payload=payload)


@router.post("/nodes/{node_id}/clear-state", response_model=NodeActionResponse)
def clear_node_state(
    node_id: str,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> NodeActionResponse:
    return service.clear_node_state(node_id=node_id)


@router.delete("/nodes/{node_id}", response_model=NodeActionResponse)
def delete_node(
    node_id: str,
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> NodeActionResponse:
    return service.delete_node(node_id=node_id)
