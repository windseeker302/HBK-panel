from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.dependencies import get_cluster_center_service
from app.main import app
from app.models.schemas import (
    AgentHeartbeatRequest,
    AgentTaskAckRequest,
    CenterTaskCreateRequest,
    ContainerInfo,
    CpuUsage,
    MemoryUsage,
    NodeRegistrationRequest,
    ProbeInitiator,
    ResourceMetrics,
    TaskStatus,
)
from app.services.monitoring import ClusterCenterService, RegisteredNode


def build_service() -> ClusterCenterService:
    service = ClusterCenterService()
    now = datetime.now(UTC)
    service._registered_nodes = {
        "node-a": RegisteredNode(
            node_id="node-a",
            node_name="Node A",
            token="token-a",
            created_at=now,
            source="bootstrap",
        ),
        "node-b": RegisteredNode(
            node_id="node-b",
            node_name="Node B",
            token="token-b",
            created_at=now,
            source="runtime",
        ),
    }
    service._tasks = {"node-a": [], "node-b": []}
    service._nodes = {}
    service._request_index = {}
    service._task_idempotency = {}
    return service


def build_heartbeat(request_id: str) -> AgentHeartbeatRequest:
    return AgentHeartbeatRequest(
        request_id=request_id,
        node_name="Node A",
        address="10.0.0.11",
        node_sampled_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        heartbeat_interval_seconds=12,
        offline_after_seconds=35,
        probe_initiator=ProbeInitiator.AGENT_SCHEDULER,
        metrics=ResourceMetrics(
            cpu=CpuUsage(percent=22.5, logical_cores=8, physical_cores=4),
            memory=MemoryUsage(
                total_bytes=16 * 1024**3,
                used_bytes=6 * 1024**3,
                available_bytes=10 * 1024**3,
                percent=37.5,
            ),
        ),
        container_runtime_available=True,
        containers=[
            ContainerInfo(
                id="abc123",
                name="api",
                image="hbk/api:latest",
                status="running",
                state="running",
                health="healthy",
            )
        ],
    )


def override_service(service: ClusterCenterService) -> TestClient:
    app.dependency_overrides[get_cluster_center_service] = lambda: service
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_register_node_returns_token_and_commands() -> None:
    client = override_service(build_service())
    response = client.post(
        "/api/center/nodes/register",
        json=NodeRegistrationRequest(
            node_id="centos-prod-01",
            node_name="CentOS 生产节点",
            address_hint="10.20.30.40",
        ).model_dump(mode="json"),
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["node_id"] == "centos-prod-01"
    assert payload["token"]
    assert 'git clone "https://github.com/windseeker302/HBK-panel.git"' in payload["commands"]["github_clone_commands"]
    assert 'cd "/opt/hbk-agent/HBK-Panel" && git pull --ff-only' in payload["commands"]["github_clone_commands"]
    assert "demo_agent.py" in payload["commands"]["run_command"]
    assert payload["commands"]["github_clone_commands"] in payload["commands"]["bootstrap_script"]
    assert "systemctl enable --now hbk-agent-centos-prod-01" in payload["commands"]["systemd_enable_commands"]
    assert 'docker build -f Dockerfile.agent -t "hbk-agent:centos-prod-01" .' in payload["commands"]["docker_build_command"]
    assert 'HBK_AGENT_IMAGE="hbk-agent:centos-prod-01"' in payload["commands"]["docker_compose_up_command"]
    assert 'HBK_NODE_ADDRESS="${HBK_NODE_ADDRESS:-10.20.30.40}"' in payload["commands"]["docker_compose_up_command"]
    assert "docker compose -f docker-compose.agent.yml up -d" in payload["commands"]["docker_compose_up_command"]


def test_duplicate_registration_returns_conflict() -> None:
    client = override_service(build_service())
    response = client.post(
        "/api/center/nodes/register",
        json=NodeRegistrationRequest(
            node_id="node-a",
            node_name="重复节点",
        ).model_dump(mode="json"),
    )
    assert response.status_code == 409


def test_agent_heartbeat_creates_online_node() -> None:
    client = override_service(build_service())
    response = client.post(
        "/api/agent/heartbeat",
        headers={"X-Node-Id": "node-a", "X-Node-Token": "token-a"},
        json=build_heartbeat("hbk-req-001").model_dump(mode="json"),
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["duplicated"] is False

    nodes_response = client.get("/api/center/nodes")
    assert nodes_response.status_code == 200
    nodes_payload = nodes_response.json()
    assert nodes_payload["online"] == 1
    assert nodes_payload["items"][0]["node_id"] == "node-a"


def test_duplicate_heartbeat_is_idempotent() -> None:
    client = override_service(build_service())
    heartbeat = build_heartbeat("hbk-req-002").model_dump(mode="json")
    headers = {"X-Node-Id": "node-a", "X-Node-Token": "token-a"}

    first = client.post("/api/agent/heartbeat", headers=headers, json=heartbeat)
    second = client.post("/api/agent/heartbeat", headers=headers, json=heartbeat)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["duplicated"] is True


def test_clear_state_keeps_registration_and_agent_can_reappear() -> None:
    client = override_service(build_service())
    headers = {"X-Node-Id": "node-a", "X-Node-Token": "token-a"}
    client.post("/api/agent/heartbeat", headers=headers, json=build_heartbeat("hbk-req-003").model_dump(mode="json"))

    clear_response = client.post("/api/center/nodes/node-a/clear-state")
    assert clear_response.status_code == 200
    assert clear_response.json()["registered"] is True

    overview = client.get("/api/center/nodes/node-a").json()
    assert overview["status"] == "abnormal"
    assert overview["server_received_at"] is None

    heartbeat_again = client.post(
        "/api/agent/heartbeat",
        headers=headers,
        json=build_heartbeat("hbk-req-004").model_dump(mode="json"),
    )
    assert heartbeat_again.status_code == 202


def test_delete_node_revokes_token_and_removes_registration() -> None:
    client = override_service(build_service())
    headers = {"X-Node-Id": "node-a", "X-Node-Token": "token-a"}
    client.post("/api/agent/heartbeat", headers=headers, json=build_heartbeat("hbk-req-005").model_dump(mode="json"))

    delete_response = client.delete("/api/center/nodes/node-a")
    assert delete_response.status_code == 200
    assert delete_response.json()["registered"] is False

    nodes_payload = client.get("/api/center/nodes").json()
    assert all(item["node_id"] != "node-a" for item in nodes_payload["items"])

    heartbeat_after_delete = client.post(
        "/api/agent/heartbeat",
        headers=headers,
        json=build_heartbeat("hbk-req-006").model_dump(mode="json"),
    )
    assert heartbeat_after_delete.status_code == 401


def test_node_becomes_abnormal_after_timeout() -> None:
    service = build_service()
    client = override_service(service)
    headers = {"X-Node-Id": "node-a", "X-Node-Token": "token-a"}
    client.post("/api/agent/heartbeat", headers=headers, json=build_heartbeat("hbk-req-007").model_dump(mode="json"))

    service._nodes["node-a"].server_received_at = datetime.now(UTC) - timedelta(seconds=50)
    response = client.get("/api/center/nodes/node-a")
    assert response.status_code == 200
    assert response.json()["status"] == "abnormal"


def test_create_pull_and_ack_task() -> None:
    client = override_service(build_service())
    create_response = client.post(
        "/api/center/nodes/node-a/tasks",
        json=CenterTaskCreateRequest(
            idempotency_key="task-001-demo",
            task_type="refresh_probe",
            payload={"reason": "manual"},
            timeout_seconds=20,
        ).model_dump(mode="json"),
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["task_id"]

    pull_response = client.get(
        "/api/agent/tasks/pull",
        headers={"X-Node-Id": "node-a", "X-Node-Token": "token-a"},
    )
    assert pull_response.status_code == 200
    assert pull_response.json()["items"][0]["task_id"] == task_id

    ack_response = client.post(
        f"/api/agent/tasks/{task_id}/ack",
        headers={"X-Node-Id": "node-a", "X-Node-Token": "token-a"},
        json=AgentTaskAckRequest(status=TaskStatus.DONE, result={"message": "ok"}).model_dump(mode="json"),
    )
    assert ack_response.status_code == 200
    assert ack_response.json()["status"] == "done"
