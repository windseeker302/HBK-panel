from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header, HTTPException, Request, status

from app.services.monitoring import ClusterCenterService


@lru_cache
def get_cluster_center_service() -> ClusterCenterService:
    return ClusterCenterService()


def get_authenticated_node_id(
    request: Request,
    node_id: str = Header(alias="X-Node-Id"),
    token: str = Header(alias="X-Node-Token"),
    service: ClusterCenterService = Depends(get_cluster_center_service),
) -> str:
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    if not service.authenticate_node(node_id=node_id, token=token, scheme=scheme):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="节点认证失败，请检查 node_id、token 或 TLS 配置",
        )
    return node_id

