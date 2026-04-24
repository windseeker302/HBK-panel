export type NodeStatus = "online" | "abnormal";
export type ProbeInitiator = "agent_scheduler" | "center_task";
export type TaskStatus = "pending" | "received" | "done" | "failed";
export type NodeAction = "clear_state" | "delete";

export interface CpuUsage {
  percent: number;
  logical_cores: number;
  physical_cores: number | null;
}

export interface MemoryUsage {
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  percent: number;
}

export interface ResourceMetrics {
  cpu: CpuUsage;
  memory: MemoryUsage;
}

export interface ContainerInfo {
  id: string;
  name: string;
  image: string;
  status: string;
  state: string;
  health: string | null;
  created_at: string | null;
}

export interface ContainerSummary {
  total: number;
  running: number;
  exited: number;
  restarting: number;
  paused: number;
  dead: number;
  unknown: number;
}

export interface NodeRuntimeSnapshot {
  node_id: string;
  node_name: string;
  address: string;
  status: NodeStatus;
  server_received_at: string | null;
  node_sampled_at: string | null;
  probe_initiator: ProbeInitiator | null;
  heartbeat_interval_seconds: number | null;
  offline_after_seconds: number | null;
  pending_tasks: number;
}

export interface NodeListItem extends NodeRuntimeSnapshot {
  cpu_percent: number | null;
  memory_percent: number | null;
  container_summary: ContainerSummary;
  container_runtime_available: boolean;
}

export interface NodeListResponse {
  items: NodeListItem[];
  total: number;
  online: number;
  abnormal: number;
}

export interface NodeOverviewResponse extends NodeRuntimeSnapshot {
  container_summary: ContainerSummary;
  container_runtime_available: boolean;
  container_runtime_message: string | null;
}

export interface NodeMetricsResponse extends NodeRuntimeSnapshot {
  metrics: ResourceMetrics | null;
}

export interface NodeContainersResponse extends NodeRuntimeSnapshot {
  container_runtime_available: boolean;
  container_runtime_message: string | null;
  summary: ContainerSummary;
  items: ContainerInfo[];
}

export interface ClusterTaskResponse {
  task_id: string;
  node_id: string;
  task_type: string;
  payload: Record<string, unknown>;
  timeout_seconds: number;
  status: TaskStatus;
  created_at: string;
  acked_at: string | null;
  result: Record<string, unknown>;
}

export interface NodeRegistrationRequest {
  node_id: string;
  node_name: string;
  address_hint?: string;
  install_path?: string;
}

export interface AgentCommandBundle {
  bootstrap_script: string;
  run_command: string;
  systemd_unit: string;
  systemd_enable_commands: string;
}

export interface NodeRegistrationResponse {
  node_id: string;
  node_name: string;
  token: string;
  address_hint: string | null;
  created_at: string;
  center_url: string;
  commands: AgentCommandBundle;
}

export interface NodeActionResponse {
  node_id: string;
  action: NodeAction;
  message: string;
  server_time: string;
  registered: boolean;
  runtime_state_cleared: boolean;
  pending_tasks: number;
}
