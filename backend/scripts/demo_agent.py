from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.schemas import AgentHeartbeatRequest, AgentTaskAckRequest, ProbeInitiator, TaskStatus
from app.services.probe import LocalProbeService


class ClusterAgentClient:
    def __init__(self, center_url: str, node_id: str, token: str, timeout_seconds: float = 5.0) -> None:
        self.center_url = center_url.rstrip("/")
        self.node_id = node_id
        self.headers = {
            "X-Node-Id": node_id,
            "X-Node-Token": token,
        }
        self.timeout_seconds = timeout_seconds

    def push_heartbeat(self, payload: AgentHeartbeatRequest) -> dict:
        return self._request_with_retry("POST", "/api/agent/heartbeat", json=payload.model_dump(mode="json"))

    def pull_tasks(self) -> dict:
        return self._request_with_retry("GET", "/api/agent/tasks/pull")

    def ack_task(self, task_id: str, status: TaskStatus, result: dict | None = None) -> dict:
        payload = AgentTaskAckRequest(status=status, result=result or {})
        return self._request_with_retry(
            "POST",
            f"/api/agent/tasks/{task_id}/ack",
            json=payload.model_dump(mode="json"),
        )

    def _request_with_retry(self, method: str, path: str, json: dict | None = None) -> dict:
        backoffs = [0.5, 1.0, 2.0]
        last_error: Exception | None = None
        for index, backoff in enumerate(backoffs, start=1):
            try:
                with httpx.Client(timeout=self.timeout_seconds, verify=False) as client:
                    response = client.request(
                        method,
                        f"{self.center_url}{path}",
                        headers=self.headers,
                        json=json,
                    )
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001 - demo agent 需要容错
                last_error = exc
                if index == len(backoffs):
                    break
                time.sleep(backoff)
        raise RuntimeError(f"请求中心节点失败：{last_error}") from last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="HBK Panel Demo Agent")
    parser.add_argument("--center-url", default=os.getenv("HBK_CENTER_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--address", default=LocalProbeService.resolve_primary_address())
    parser.add_argument("--interval", type=int, default=12)
    parser.add_argument("--offline-after", type=int, default=35)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--auto-ack", action="store_true")
    args = parser.parse_args()

    collector = LocalProbeService()
    client = ClusterAgentClient(center_url=args.center_url, node_id=args.node_id, token=args.token)

    while True:
        metrics, container_available, container_message, containers = collector.collect_snapshot()
        heartbeat = AgentHeartbeatRequest(
            request_id=f"{args.node_id}-{uuid.uuid4()}",
            node_name=args.node_name,
            address=args.address,
            node_sampled_at=datetime.now(UTC),
            heartbeat_interval_seconds=args.interval,
            offline_after_seconds=args.offline_after,
            probe_initiator=ProbeInitiator.AGENT_SCHEDULER,
            metrics=metrics,
            container_runtime_available=container_available,
            container_runtime_message=container_message,
            containers=containers,
        )
        response = client.push_heartbeat(heartbeat)
        print(
            f"[{datetime.now().isoformat()}] heartbeat accepted={response['accepted']} "
            f"duplicated={response['duplicated']} pending_tasks={response['pending_tasks']}"
        )

        if args.auto_ack:
            pulled = client.pull_tasks()
            for task in pulled["items"]:
                client.ack_task(
                    task_id=task["task_id"],
                    status=TaskStatus.DONE,
                    result={"message": "demo agent 已接收并完成占位任务"},
                )

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
