import type {
  ClusterTaskResponse,
  NodeActionResponse,
  NodeContainersResponse,
  NodeListResponse,
  NodeMetricsResponse,
  NodeOverviewResponse,
  NodeRegistrationRequest,
  NodeRegistrationResponse,
} from "@/lib/types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

function generateIdempotencyKey() {
  const webCrypto = globalThis.crypto;

  if (typeof webCrypto?.randomUUID === "function") {
    return webCrypto.randomUUID();
  }

  if (typeof webCrypto?.getRandomValues === "function") {
    const bytes = webCrypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;

    const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  return `fallback-${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `请求失败：${response.status}`);
  }

  return (await response.json()) as T;
}

export function fetchNodes() {
  return request<NodeListResponse>("/api/center/nodes");
}

export function fetchNodeOverview(nodeId: string) {
  return request<NodeOverviewResponse>(`/api/center/nodes/${nodeId}`);
}

export function fetchNodeMetrics(nodeId: string) {
  return request<NodeMetricsResponse>(`/api/center/nodes/${nodeId}/metrics`);
}

export function fetchNodeContainers(nodeId: string) {
  return request<NodeContainersResponse>(`/api/center/nodes/${nodeId}/containers`);
}

export function dispatchRefreshTask(nodeId: string) {
  return request<ClusterTaskResponse>(`/api/center/nodes/${nodeId}/tasks`, {
    method: "POST",
    body: JSON.stringify({
      idempotency_key: generateIdempotencyKey(),
      task_type: "refresh_probe",
      payload: {
        initiator: "center_manual",
      },
      timeout_seconds: 20,
    }),
  });
}

export function registerNode(payload: NodeRegistrationRequest) {
  return request<NodeRegistrationResponse>("/api/center/nodes/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function clearNodeState(nodeId: string) {
  return request<NodeActionResponse>(`/api/center/nodes/${nodeId}/clear-state`, {
    method: "POST",
  });
}

export function deleteNode(nodeId: string) {
  return request<NodeActionResponse>(`/api/center/nodes/${nodeId}`, {
    method: "DELETE",
  });
}
