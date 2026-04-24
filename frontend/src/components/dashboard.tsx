import { type FormEvent, useEffect, useState, useTransition } from "react";
import {
  Activity,
  Boxes,
  ChevronDown,
  ChevronUp,
  ClipboardCopy,
  Cpu,
  HardDrive,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  Server,
  ShieldCheck,
  TimerReset,
  Trash2,
  X,
} from "lucide-react";

import {
  clearNodeState,
  deleteNode,
  dispatchRefreshTask,
  fetchNodeContainers,
  fetchNodeMetrics,
  fetchNodeOverview,
  fetchNodes,
  registerNode,
} from "@/lib/api";
import type {
  NodeContainersResponse,
  NodeListItem,
  NodeMetricsResponse,
  NodeOverviewResponse,
  NodeRegistrationResponse,
  NodeStatus,
  ProbeInitiator,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const DEFAULT_AGENT_REPO_URL = (import.meta.env.VITE_AGENT_REPO_URL ?? "https://github.com/windseeker302/HBK-panel.git").trim();

function formatBytes(value: number) {
  if (value <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTime(value: string | null) {
  if (!value) {
    return "未上报";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function formatAgo(value: string | null) {
  if (!value) {
    return "未收到心跳";
  }

  const diff = Math.max(0, Date.now() - new Date(value).getTime());
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) {
    return `${seconds} 秒前`;
  }

  const minutes = Math.floor(seconds / 60);
  return `${minutes} 分钟前`;
}

function statusVariant(status: NodeStatus) {
  return status === "online" ? "success" : "danger";
}

function statusLabel(status: NodeStatus) {
  return status === "online" ? "在线" : "异常";
}

function initiatorLabel(value: ProbeInitiator | null) {
  if (value === "center_task") {
    return "中心任务";
  }
  if (value === "agent_scheduler") {
    return "Agent 定时器";
  }
  return "未上报";
}

function summaryBadges(containerData: NodeContainersResponse | null) {
  if (!containerData) {
    return [];
  }

  return [
    { label: "运行中", value: containerData.summary.running, variant: "success" as const },
    { label: "已退出", value: containerData.summary.exited, variant: "warning" as const },
    { label: "重启中", value: containerData.summary.restarting, variant: "danger" as const },
    { label: "暂停", value: containerData.summary.paused, variant: "outline" as const },
    { label: "异常", value: containerData.summary.dead + containerData.summary.unknown, variant: "danger" as const },
  ];
}

function normalizeInstallPath(value: string) {
  const trimmed = value.trim();
  return trimmed || "/opt/hbk-agent/HBK-Panel";
}

function getInstallParentPath(value: string) {
  const normalized = normalizeInstallPath(value).replace(/\/+$/, "");
  const index = normalized.lastIndexOf("/");
  if (index > 0) {
    return normalized.slice(0, index);
  }
  if (index === 0) {
    return "/";
  }
  return ".";
}

function buildGithubCloneCommands(installPath: string) {
  const normalized = normalizeInstallPath(installPath);
  const parent = getInstallParentPath(normalized);
  return [
    `mkdir -p "${parent}"`,
    `if [ -d "${normalized}/.git" ]; then cd "${normalized}" && git pull --ff-only; else git clone "${DEFAULT_AGENT_REPO_URL}" "${normalized}"; fi`,
  ].join("\n");
}

interface CommandBlockProps {
  title: string;
  value: string;
  onCopy: (value: string, title: string) => Promise<void>;
}

function CommandBlock({ title, value, onCopy }: CommandBlockProps) {
  return (
    <div className="space-y-3 rounded-[24px] border border-border/70 bg-secondary/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-slate-900">{title}</div>
        <Button variant="outline" size="sm" onClick={() => void onCopy(value, title)}>
          <ClipboardCopy className="h-4 w-4" />
          复制
        </Button>
      </div>
      <textarea
        readOnly
        value={value}
        className="min-h-32 w-full rounded-2xl border border-border/70 bg-white/80 p-4 font-mono text-xs leading-6 text-slate-700 outline-none"
      />
    </div>
  );
}

type InstallPlan = "python" | "docker";
type LoadOptions = {
  silent?: boolean;
};
type SectionKey = "nodeList" | "timeline" | "cpu" | "memory" | "containers" | "rules" | "lifecycle";

const DEFAULT_COLLAPSED_SECTIONS: Record<SectionKey, boolean> = {
  nodeList: false,
  timeline: false,
  cpu: false,
  memory: false,
  containers: false,
  rules: true,
  lifecycle: true,
};

interface SectionToggleButtonProps {
  collapsed: boolean;
  onToggle: () => void;
}

function SectionToggleButton({ collapsed, onToggle }: SectionToggleButtonProps) {
  return (
    <Button type="button" variant="ghost" size="sm" onClick={onToggle} aria-expanded={!collapsed}>
      {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
      {collapsed ? "展开" : "收起"}
    </Button>
  );
}

export function Dashboard() {
  const [nodes, setNodes] = useState<NodeListItem[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [overview, setOverview] = useState<NodeOverviewResponse | null>(null);
  const [metrics, setMetrics] = useState<NodeMetricsResponse | null>(null);
  const [containerData, setContainerData] = useState<NodeContainersResponse | null>(null);
  const [pageError, setPageError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [hostsLoading, setHostsLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [hostsRefreshing, setHostsRefreshing] = useState(false);
  const [detailRefreshing, setDetailRefreshing] = useState(false);
  const [hasLoadedNodesOnce, setHasLoadedNodesOnce] = useState(false);
  const [taskLoading, setTaskLoading] = useState(false);
  const [nodeActionLoading, setNodeActionLoading] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [showRegisterModal, setShowRegisterModal] = useState(false);
  const [registrationError, setRegistrationError] = useState("");
  const [registrationResult, setRegistrationResult] = useState<NodeRegistrationResponse | null>(null);
  const [selectedInstallPlan, setSelectedInstallPlan] = useState<InstallPlan>("python");
  const [copyMessage, setCopyMessage] = useState("");
  const [isPending, startTransition] = useTransition();
  const [collapsedSections, setCollapsedSections] = useState<Record<SectionKey, boolean>>(DEFAULT_COLLAPSED_SECTIONS);
  const [registerForm, setRegisterForm] = useState({
    nodeId: "",
    nodeName: "",
    addressHint: "",
    installPath: "/opt/hbk-agent/HBK-Panel",
    centerUrl: "",
  });

  const currentNode = nodes.find((item) => item.node_id === selectedNodeId) ?? null;
  const totalPending = nodes.reduce((sum, item) => sum + item.pending_tasks, 0);
  const onlineNodeCount = nodes.filter((item) => item.status === "online").length;
  const abnormalNodeCount = nodes.length - onlineNodeCount;
  const githubCloneCommands = registrationResult
    ? registrationResult.commands.github_clone_commands?.trim() || buildGithubCloneCommands(registerForm.installPath)
    : "";
  const isLocalCenterUrl = registrationResult
    ? /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?(\/|$)/i.test(registrationResult.center_url)
    : false;
  const isRefreshing = hostsRefreshing || detailRefreshing;
  const refreshDisabled = hostsLoading || detailLoading || isRefreshing || isPending;
  const toggleSection = (section: SectionKey) => {
    setCollapsedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const loadNodes = async ({ silent = false }: LoadOptions = {}) => {
    const useBlockingLoading = !silent && !hasLoadedNodesOnce;

    if (useBlockingLoading) {
      setHostsLoading(true);
    } else {
      setHostsRefreshing(true);
    }

    try {
      const data = await fetchNodes();
      setPageError("");
      setNodes(data.items);
      setHasLoadedNodesOnce(true);
      startTransition(() => {
        setSelectedNodeId((prev) => {
          if (prev && data.items.some((item) => item.node_id === prev)) {
            return prev;
          }
          return data.items[0]?.node_id ?? "";
        });
      });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "加载节点列表失败");
    } finally {
      if (useBlockingLoading) {
        setHostsLoading(false);
      } else {
        setHostsRefreshing(false);
      }
    }
  };

  const loadNodeDetail = async (nodeId: string, { silent = false }: LoadOptions = {}) => {
    const hasCurrentNodeDetail =
      overview?.node_id === nodeId &&
      metrics?.node_id === nodeId &&
      containerData?.node_id === nodeId;
    const useBlockingLoading = !silent || !hasCurrentNodeDetail;

    if (useBlockingLoading) {
      setDetailLoading(true);
    } else {
      setDetailRefreshing(true);
    }

    try {
      const [overviewResponse, metricsResponse, containerResponse] = await Promise.all([
        fetchNodeOverview(nodeId),
        fetchNodeMetrics(nodeId),
        fetchNodeContainers(nodeId),
      ]);
      setDetailError("");
      setOverview(overviewResponse);
      setMetrics(metricsResponse);
      setContainerData(containerResponse);
    } catch (error) {
      if (useBlockingLoading) {
        setOverview(null);
        setMetrics(null);
        setContainerData(null);
      }
      setDetailError(error instanceof Error ? error.message : "加载节点详情失败");
    } finally {
      if (useBlockingLoading) {
        setDetailLoading(false);
      } else {
        setDetailRefreshing(false);
      }
    }
  };

  useEffect(() => {
    void loadNodes();
  }, []);

  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }
    void loadNodeDetail(selectedNodeId);
  }, [selectedNodeId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadNodes({ silent: true });
      if (selectedNodeId) {
        void loadNodeDetail(selectedNodeId, { silent: true });
      }
    }, 10000);

    return () => window.clearInterval(timer);
  }, [selectedNodeId]);

  const sampledAt = overview?.server_received_at ?? metrics?.server_received_at ?? containerData?.server_received_at ?? null;

  const handleDispatchTask = async () => {
    if (!selectedNodeId) {
      return;
    }

    setTaskLoading(true);
    setActionMessage("");

    try {
      const task = await dispatchRefreshTask(selectedNodeId);
      setActionMessage(`已向 ${task.node_id} 下发任务：${task.task_type}`);
      await loadNodes();
      await loadNodeDetail(selectedNodeId);
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : "任务下发失败");
    } finally {
      setTaskLoading(false);
    }
  };

  const handleClearNodeState = async () => {
    if (!selectedNodeId || !currentNode) {
      return;
    }

    const confirmed = window.confirm(
      `确定清理节点 ${currentNode.node_name} 的运行态缓存吗？\n\n这不会删除注册信息和 token。下一次 Agent 心跳后，该节点会重新出现。`,
    );
    if (!confirmed) {
      return;
    }

    setNodeActionLoading(true);
    setActionMessage("");

    try {
      const result = await clearNodeState(selectedNodeId);
      setActionMessage(result.message);
      await loadNodes();
      await loadNodeDetail(selectedNodeId);
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : "清理节点状态失败");
    } finally {
      setNodeActionLoading(false);
    }
  };

  const handleDeleteNode = async () => {
    if (!selectedNodeId || !currentNode) {
      return;
    }

    const confirmed = window.confirm(
      `确定注销节点 ${currentNode.node_name} 吗？\n\n这会把节点从中心注册表移除，并立即废掉 token。之后该 Agent 再发心跳会直接返回 401。`,
    );
    if (!confirmed) {
      return;
    }

    setNodeActionLoading(true);
    setActionMessage("");

    try {
      const result = await deleteNode(selectedNodeId);
      setActionMessage(result.message);
      setSelectedNodeId("");
      setOverview(null);
      setMetrics(null);
      setContainerData(null);
      await loadNodes();
    } catch (error) {
      setActionMessage(error instanceof Error ? error.message : "注销节点失败");
    } finally {
      setNodeActionLoading(false);
    }
  };

  const handleRegisterNode = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRegistering(true);
    setRegistrationError("");
    setCopyMessage("");

    try {
      const result = await registerNode({
        node_id: registerForm.nodeId.trim(),
        node_name: registerForm.nodeName.trim(),
        address_hint: registerForm.addressHint.trim() || undefined,
        install_path: registerForm.installPath.trim(),
        center_url: registerForm.centerUrl.trim() || undefined,
      });
      setRegistrationResult(result);
      setSelectedInstallPlan("python");
      setActionMessage(`节点 ${result.node_name} 已注册，等待 Agent 首次心跳。`);
      setSelectedNodeId(result.node_id);
      await loadNodes();
      await loadNodeDetail(result.node_id);
    } catch (error) {
      setRegistrationError(error instanceof Error ? error.message : "节点注册失败");
    } finally {
      setRegistering(false);
    }
  };

  const handleCopy = async (value: string, title: string) => {
    await navigator.clipboard.writeText(value);
    setCopyMessage(`${title}已复制到剪贴板`);
  };

  const resetRegisterModal = () => {
    setShowRegisterModal(false);
    setRegistrationError("");
    setRegistrationResult(null);
    setSelectedInstallPlan("python");
    setCopyMessage("");
    setRegisterForm({
      nodeId: "",
      nodeName: "",
      addressHint: "",
      installPath: "/opt/hbk-agent/HBK-Panel",
      centerUrl: "",
    });
  };

  return (
    <div className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-8">
        <header className="relative overflow-hidden rounded-[36px] border border-white/60 bg-[radial-gradient(circle_at_top_left,_rgba(49,135,125,0.24),_transparent_35%),linear-gradient(135deg,_rgba(255,255,255,0.86),_rgba(247,243,236,0.88))] p-8 shadow-panel animate-floatUp">
          <div className="absolute -right-16 top-8 h-40 w-40 rounded-full bg-primary/10 blur-3xl" />
          <div className="absolute bottom-0 left-1/3 h-24 w-24 rounded-full bg-[#f0b45b]/20 blur-2xl" />
          <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="space-y-3">
              <Badge variant="outline" className="w-fit border-primary/20 bg-white/65 uppercase tracking-[0.24em] text-primary">
                HBK Cluster Center
              </Badge>
              <div className="space-y-2">
                <h1 className="max-w-4xl text-4xl font-semibold tracking-tight text-slate-900 md:text-5xl">
                  多节点轻量监控集群中心
                </h1>
                <p className="max-w-3xl text-sm leading-7 text-slate-600 md:text-base">
                  采用 Agent 主动上报为主、中心任务下发为辅的通信模型，统一汇总 CPU、内存、容器状态与节点在线性。
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="rounded-full border border-white/60 bg-white/70 px-4 py-2 text-sm text-slate-600 backdrop-blur-sm">
                {sampledAt ? `中心最近收包：${formatTime(sampledAt)}` : "等待 Agent 首次心跳"}
              </div>
              <Button variant="outline" onClick={() => setShowRegisterModal(true)}>
                <Plus className="h-4 w-4" />
                新增节点
              </Button>
              <Button
                variant="default"
                onClick={() => {
                  void loadNodes({ silent: true });
                  if (selectedNodeId) {
                    void loadNodeDetail(selectedNodeId, { silent: true });
                  }
                }}
                disabled={refreshDisabled}
              >
                <RefreshCw className={`h-4 w-4 ${refreshDisabled ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>
          </div>
        </header>

        <div className="grid gap-4 md:grid-cols-4">
          <Card className="animate-floatUp">
            <CardContent className="flex items-center justify-between p-6">
              <div>
                <div className="text-sm text-muted-foreground">总节点</div>
                <div className="mt-2 text-3xl font-semibold">{nodes.length}</div>
              </div>
              <Server className="h-8 w-8 text-primary" />
            </CardContent>
          </Card>
          <Card className="animate-floatUp">
            <CardContent className="flex items-center justify-between p-6">
              <div>
                <div className="text-sm text-muted-foreground">在线节点</div>
                <div className="mt-2 text-3xl font-semibold">{onlineNodeCount}</div>
              </div>
              <Activity className="h-8 w-8 text-emerald-600" />
            </CardContent>
          </Card>
          <Card className="animate-floatUp">
            <CardContent className="flex items-center justify-between p-6">
              <div>
                <div className="text-sm text-muted-foreground">异常节点</div>
                <div className="mt-2 text-3xl font-semibold">{abnormalNodeCount}</div>
              </div>
              <TimerReset className="h-8 w-8 text-rose-600" />
            </CardContent>
          </Card>
          <Card className="animate-floatUp">
            <CardContent className="flex items-center justify-between p-6">
              <div>
                <div className="text-sm text-muted-foreground">待处理任务</div>
                <div className="mt-2 text-3xl font-semibold">{totalPending}</div>
              </div>
              <Send className="h-8 w-8 text-amber-600" />
            </CardContent>
          </Card>
        </div>

        {pageError ? (
          <Card className="animate-floatUp">
            <CardHeader>
              <CardTitle>加载失败</CardTitle>
              <CardDescription>{pageError}</CardDescription>
            </CardHeader>
          </Card>
        ) : null}

        {actionMessage ? (
          <Card className="animate-floatUp">
            <CardContent className="p-6 text-sm text-slate-700">{actionMessage}</CardContent>
          </Card>
        ) : null}

        <div className="grid items-start gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="animate-floatUp">
            <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
              <div className="space-y-2">
                <CardTitle className="flex items-center gap-2">
                  <Server className="h-5 w-5 text-primary" />
                  节点列表
                </CardTitle>
                <CardDescription>
                  {collapsedSections.nodeList ? `共 ${nodes.length} 个节点，在线 ${onlineNodeCount} 个，异常 ${abnormalNodeCount} 个。` : "展示心跳状态、采样时间和容器运行概况。"}
                </CardDescription>
              </div>
              <SectionToggleButton
                collapsed={collapsedSections.nodeList}
                onToggle={() => toggleSection("nodeList")}
              />
            </CardHeader>
            {!collapsedSections.nodeList ? (
            <CardContent className="space-y-3">
              {hostsLoading ? (
                <div className="rounded-3xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  正在加载节点列表...
                </div>
              ) : null}

              {nodes.map((node, index) => {
                const active = node.node_id === selectedNodeId;
                return (
                  <button
                    key={node.node_id}
                    type="button"
                    onClick={() => setSelectedNodeId(node.node_id)}
                    className={`w-full rounded-[26px] border p-4 text-left transition-all ${
                      active
                        ? "border-primary/30 bg-primary/10 shadow-sm"
                        : "border-border/60 bg-white/70 hover:border-primary/20 hover:bg-white"
                    }`}
                    style={{ animationDelay: `${index * 0.08}s` }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-2">
                        <div className="text-lg font-medium text-slate-900">{node.node_name}</div>
                        <div className="text-sm text-slate-500">{node.address}</div>
                      </div>
                      <Badge variant={statusVariant(node.status)}>{statusLabel(node.status)}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge variant="secondary">CPU {node.cpu_percent?.toFixed(1) ?? "--"}%</Badge>
                      <Badge variant="outline">容器 {node.container_summary.total}</Badge>
                      <Badge variant="outline">任务 {node.pending_tasks}</Badge>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      上次心跳：{formatAgo(node.server_received_at)}，发起方：{initiatorLabel(node.probe_initiator)}
                    </p>
                  </button>
                );
              })}
            </CardContent>
            ) : null}
          </Card>

          <div className="space-y-6">
            <Card className="animate-floatUp">
              <CardHeader className="gap-4 md:flex-row md:items-end md:justify-between">
                <div className="space-y-2">
                  <CardTitle className="flex items-center gap-2">
                    <ShieldCheck className="h-5 w-5 text-primary" />
                    节点时序与通信语义
                  </CardTitle>
                  <CardDescription>
                    {collapsedSections.timeline
                      ? (currentNode ? `当前查看 ${currentNode.node_name}，最近收包 ${formatTime(overview?.server_received_at ?? null)}` : "请选择节点")
                      : (currentNode ? `当前查看节点：${currentNode.node_name}` : "请选择节点")}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-3">
                  <SectionToggleButton
                    collapsed={collapsedSections.timeline}
                    onToggle={() => toggleSection("timeline")}
                  />
                  <Button variant="outline" onClick={handleDispatchTask} disabled={!selectedNodeId || taskLoading}>
                    <Send className={`h-4 w-4 ${taskLoading ? "animate-pulse" : ""}`} />
                    下发采样任务
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleClearNodeState}
                    disabled={!selectedNodeId || nodeActionLoading}
                  >
                    <RotateCcw className={`h-4 w-4 ${nodeActionLoading ? "animate-spin" : ""}`} />
                    清理状态
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleDeleteNode}
                    disabled={!selectedNodeId || nodeActionLoading}
                    className="border-rose-200 text-rose-700 hover:bg-rose-50 hover:text-rose-800"
                  >
                    <Trash2 className="h-4 w-4" />
                    注销节点
                  </Button>
                </div>
              </CardHeader>
              {!collapsedSections.timeline ? (
              <CardContent className="grid gap-3 md:grid-cols-3">
                <div className="rounded-[22px] bg-secondary/80 p-4">
                  <div className="text-sm text-muted-foreground">Agent 时间</div>
                  <div className="mt-2 text-base font-semibold text-slate-900">{formatTime(overview?.node_sampled_at ?? null)}</div>
                  <p className="mt-2 text-sm text-muted-foreground">保留节点本地采样时间，便于判断时钟偏差。</p>
                </div>
                <div className="rounded-[22px] bg-secondary/80 p-4">
                  <div className="text-sm text-muted-foreground">中心收包时间</div>
                  <div className="mt-2 text-base font-semibold text-slate-900">{formatTime(overview?.server_received_at ?? null)}</div>
                  <p className="mt-2 text-sm text-muted-foreground">服务端接收时间单独存储，用于离线判定和时序分析。</p>
                </div>
                <div className="rounded-[22px] bg-secondary/80 p-4">
                  <div className="text-sm text-muted-foreground">最新探测发起方</div>
                  <div className="mt-2 text-base font-semibold text-slate-900">{initiatorLabel(overview?.probe_initiator ?? null)}</div>
                  <p className="mt-2 text-sm text-muted-foreground">
                    心跳 {overview?.heartbeat_interval_seconds ?? "--"} 秒，离线阈值 {overview?.offline_after_seconds ?? "--"} 秒。
                  </p>
                </div>
              </CardContent>
              ) : null}
            </Card>

            <div className="grid items-start gap-6 md:grid-cols-2">
              <Card className="animate-floatUp">
                <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-2">
                    <CardTitle className="flex items-center gap-2">
                      <Cpu className="h-5 w-5 text-primary" />
                      CPU 使用率
                    </CardTitle>
                    <CardDescription>
                      {collapsedSections.cpu
                        ? `当前 ${metrics?.metrics ? `${metrics.metrics.cpu.percent.toFixed(1)}%` : "--"}`
                        : (currentNode ? `${currentNode.node_name} 的 CPU 实时概况` : "请选择节点")}
                    </CardDescription>
                  </div>
                  <SectionToggleButton
                    collapsed={collapsedSections.cpu}
                    onToggle={() => toggleSection("cpu")}
                  />
                </CardHeader>
                {!collapsedSections.cpu ? (
                <CardContent className="space-y-6">
                  <div>
                    <div className="mb-2 flex items-end justify-between">
                      <span className="text-sm text-muted-foreground">当前占用</span>
                      <span className="text-3xl font-semibold text-slate-900">
                        {metrics?.metrics ? `${metrics.metrics.cpu.percent.toFixed(1)}%` : "--"}
                      </span>
                    </div>
                    <Progress value={metrics?.metrics?.cpu.percent ?? 0} />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-[22px] bg-secondary/80 p-4">
                      <div className="text-sm text-muted-foreground">逻辑核心</div>
                      <div className="mt-2 text-2xl font-semibold">{metrics?.metrics?.cpu.logical_cores ?? "--"}</div>
                    </div>
                    <div className="rounded-[22px] bg-secondary/80 p-4">
                      <div className="text-sm text-muted-foreground">物理核心</div>
                      <div className="mt-2 text-2xl font-semibold">{metrics?.metrics?.cpu.physical_cores ?? "--"}</div>
                    </div>
                  </div>
                </CardContent>
                ) : null}
              </Card>

              <Card className="animate-floatUp">
                <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-2">
                    <CardTitle className="flex items-center gap-2">
                      <HardDrive className="h-5 w-5 text-primary" />
                      内存使用率
                    </CardTitle>
                    <CardDescription>
                      {collapsedSections.memory
                        ? `当前 ${metrics?.metrics ? `${metrics.metrics.memory.percent.toFixed(1)}%` : "--"}`
                        : "显示总量、已用和可用内存。"}
                    </CardDescription>
                  </div>
                  <SectionToggleButton
                    collapsed={collapsedSections.memory}
                    onToggle={() => toggleSection("memory")}
                  />
                </CardHeader>
                {!collapsedSections.memory ? (
                <CardContent className="space-y-6">
                  <div>
                    <div className="mb-2 flex items-end justify-between">
                      <span className="text-sm text-muted-foreground">当前占用</span>
                      <span className="text-3xl font-semibold text-slate-900">
                        {metrics?.metrics ? `${metrics.metrics.memory.percent.toFixed(1)}%` : "--"}
                      </span>
                    </div>
                    <Progress value={metrics?.metrics?.memory.percent ?? 0} indicatorClassName="from-[#f0b45b] to-[#d0704b]" />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-[22px] bg-secondary/80 p-4">
                      <div className="text-sm text-muted-foreground">总内存</div>
                      <div className="mt-2 text-lg font-semibold">
                        {metrics?.metrics ? formatBytes(metrics.metrics.memory.total_bytes) : "--"}
                      </div>
                    </div>
                    <div className="rounded-[22px] bg-secondary/80 p-4">
                      <div className="text-sm text-muted-foreground">已使用</div>
                      <div className="mt-2 text-lg font-semibold">
                        {metrics?.metrics ? formatBytes(metrics.metrics.memory.used_bytes) : "--"}
                      </div>
                    </div>
                    <div className="rounded-[22px] bg-secondary/80 p-4">
                      <div className="text-sm text-muted-foreground">可用</div>
                      <div className="mt-2 text-lg font-semibold">
                        {metrics?.metrics ? formatBytes(metrics.metrics.memory.available_bytes) : "--"}
                      </div>
                    </div>
                  </div>
                </CardContent>
                ) : null}
              </Card>
            </div>

            <Card className="animate-floatUp">
              <CardHeader className="gap-4 md:flex-row md:items-end md:justify-between">
                <div className="space-y-2">
                  <CardTitle className="flex items-center gap-2">
                    <Boxes className="h-5 w-5 text-primary" />
                    容器状态
                  </CardTitle>
                  <CardDescription>
                    {containerData?.container_runtime_available
                      ? `共发现 ${containerData.summary.total} 个容器`
                      : "当容器运行时不可用时，中心保留节点上报的原因说明。"}
                  </CardDescription>
                </div>
                <div className="flex flex-wrap gap-2">
                  <SectionToggleButton
                    collapsed={collapsedSections.containers}
                    onToggle={() => toggleSection("containers")}
                  />
                  {summaryBadges(containerData).map((item) => (
                    <Badge key={item.label} variant={item.variant}>
                      {item.label} {item.value}
                    </Badge>
                  ))}
                </div>
              </CardHeader>
              {!collapsedSections.containers ? (
              <CardContent className="space-y-4">
                {detailError ? (
                  <div className="rounded-[24px] border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{detailError}</div>
                ) : null}

                {detailLoading ? (
                  <div className="rounded-[24px] border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                    正在加载节点详情...
                  </div>
                ) : null}

                {containerData && !containerData.container_runtime_available ? (
                  <div className="rounded-[24px] border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
                    {containerData.container_runtime_message ?? "节点未启用容器运行时。"}
                  </div>
                ) : null}

                {containerData?.container_runtime_available && containerData.items.length === 0 ? (
                  <div className="rounded-[24px] border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                    {containerData.container_runtime_message ?? "当前没有容器。"}
                  </div>
                ) : null}

                {containerData?.container_runtime_available && containerData.items.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>容器</TableHead>
                        <TableHead>镜像</TableHead>
                        <TableHead>状态</TableHead>
                        <TableHead>健康检查</TableHead>
                        <TableHead>创建时间</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {containerData.items.map((container) => (
                        <TableRow key={container.id}>
                          <TableCell>
                            <div className="flex flex-col">
                              <span className="font-medium text-slate-900">{container.name}</span>
                              <span className="text-xs text-muted-foreground">{container.id}</span>
                            </div>
                          </TableCell>
                          <TableCell className="font-mono text-xs">{container.image}</TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                container.state === "running"
                                  ? "success"
                                  : container.state === "exited"
                                    ? "warning"
                                    : "outline"
                              }
                            >
                              {container.status}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {container.health ? <Badge variant="secondary">{container.health}</Badge> : "-"}
                          </TableCell>
                          <TableCell>{formatTime(container.created_at)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : null}
              </CardContent>
              ) : null}
            </Card>

            <div className="grid items-start gap-6 lg:grid-cols-2">
              <Card className="animate-floatUp">
                <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-2">
                    <CardTitle className="flex items-center gap-2">
                      <Activity className="h-5 w-5 text-primary" />
                      通信规则
                    </CardTitle>
                    <CardDescription>
                      {collapsedSections.rules ? "保留心跳、离线判定、认证与幂等约束摘要。" : "页面直接映射轻量监控集群的核心约束。"}
                    </CardDescription>
                  </div>
                  <SectionToggleButton
                    collapsed={collapsedSections.rules}
                    onToggle={() => toggleSection("rules")}
                  />
                </CardHeader>
                {!collapsedSections.rules ? (
                <CardContent className="grid gap-3">
                  <div className="rounded-[22px] bg-secondary/80 p-4 text-sm leading-7 text-slate-700">
                    Agent 以 10~15 秒心跳主动推送，中心 30~45 秒未收到即标记节点异常。
                  </div>
                  <div className="rounded-[22px] bg-secondary/80 p-4 text-sm leading-7 text-slate-700">
                    传输协议统一为 HTTP/HTTPS + JSON，认证依赖 node_id + token，生产环境建议强制 TLS。
                  </div>
                  <div className="rounded-[22px] bg-secondary/80 p-4 text-sm leading-7 text-slate-700">
                    Agent 侧采用超时、重试、退避与 request_id 幂等键，中心下发任务支持 idempotency_key 去重。
                  </div>
                </CardContent>
                ) : null}
              </Card>

              <Card className="animate-floatUp">
                <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-2">
                    <CardTitle className="flex items-center gap-2">
                      <Send className="h-5 w-5 text-primary" />
                      节点生命周期
                    </CardTitle>
                    <CardDescription>
                      {collapsedSections.lifecycle ? "支持清理运行态和真正注销节点两种动作。" : "现在支持“清理状态”和“注销节点”两种动作。"}
                    </CardDescription>
                  </div>
                  <SectionToggleButton
                    collapsed={collapsedSections.lifecycle}
                    onToggle={() => toggleSection("lifecycle")}
                  />
                </CardHeader>
                {!collapsedSections.lifecycle ? (
                <CardContent className="grid gap-3">
                  <div className="rounded-[22px] bg-secondary/80 p-4">
                    <div className="font-medium text-slate-900">POST /api/center/nodes/{`{id}`}/clear-state</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      只清掉中心内存中的运行态缓存，不删除注册信息，也不会废掉 token。Agent 下次心跳后会重新出现。
                    </p>
                  </div>
                  <div className="rounded-[22px] bg-secondary/80 p-4">
                    <div className="font-medium text-slate-900">DELETE /api/center/nodes/{`{id}`}</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      从中心注册表移除节点，并立即废掉 token。之后该 Agent 再发心跳会直接返回 401。
                    </p>
                  </div>
                  <div className="rounded-[22px] bg-secondary/80 p-4">
                    <div className="font-medium text-slate-900">POST /api/center/nodes/register</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      前端可重新注册节点，并生成新的 token 与 CentOS 启动命令。
                    </p>
                  </div>
                </CardContent>
                ) : null}
              </Card>
            </div>
          </div>
        </div>
      </div>

      {showRegisterModal ? (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/35 p-4 backdrop-blur-sm md:p-6">
          <div className="flex min-h-full items-start justify-center">
            <div className="my-4 flex w-full max-w-4xl flex-col overflow-hidden rounded-[32px] border border-white/70 bg-background shadow-panel md:my-8 md:max-h-[calc(100vh-4rem)]">
              <div className="flex shrink-0 items-center justify-between border-b border-border/60 px-6 py-5">
              <div>
                <div className="text-xl font-semibold text-slate-900">新增节点</div>
                <div className="mt-1 text-sm text-muted-foreground">先完成中心注册，再去目标主机执行轻量 Agent 启动命令。</div>
              </div>
              <button
                type="button"
                onClick={resetRegisterModal}
                className="rounded-full border border-border/70 p-2 text-slate-500 transition hover:bg-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {!registrationResult ? (
              <form className="space-y-5 overflow-y-auto p-6" onSubmit={handleRegisterNode}>
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-800">节点 ID</span>
                    <input
                      required
                      value={registerForm.nodeId}
                      onChange={(event) => setRegisterForm((prev) => ({ ...prev, nodeId: event.target.value }))}
                      placeholder="例如：centos-prod-01"
                      className="h-11 w-full rounded-2xl border border-border/70 bg-white/80 px-4 text-sm outline-none transition focus:border-primary"
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-800">节点名称</span>
                    <input
                      required
                      value={registerForm.nodeName}
                      onChange={(event) => setRegisterForm((prev) => ({ ...prev, nodeName: event.target.value }))}
                      placeholder="例如：华南生产节点"
                      className="h-11 w-full rounded-2xl border border-border/70 bg-white/80 px-4 text-sm outline-none transition focus:border-primary"
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-800">地址提示</span>
                    <input
                      value={registerForm.addressHint}
                      onChange={(event) => setRegisterForm((prev) => ({ ...prev, addressHint: event.target.value }))}
                      placeholder="例如：10.20.30.40"
                      className="h-11 w-full rounded-2xl border border-border/70 bg-white/80 px-4 text-sm outline-none transition focus:border-primary"
                    />
                  </label>
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-800">安装目录</span>
                    <input
                      value={registerForm.installPath}
                      onChange={(event) => setRegisterForm((prev) => ({ ...prev, installPath: event.target.value }))}
                      className="h-11 w-full rounded-2xl border border-border/70 bg-white/80 px-4 text-sm outline-none transition focus:border-primary"
                    />
                  </label>
                  <label className="space-y-2 md:col-span-2">
                    <span className="text-sm font-medium text-slate-800">Agent 访问中心地址（可选）</span>
                    <input
                      value={registerForm.centerUrl}
                      onChange={(event) => setRegisterForm((prev) => ({ ...prev, centerUrl: event.target.value }))}
                      placeholder="例如：http://10.20.30.40:8000"
                      className="h-11 w-full rounded-2xl border border-border/70 bg-white/80 px-4 text-sm outline-none transition focus:border-primary"
                    />
                    <div className="text-xs leading-6 text-muted-foreground">
                      留空时会依次使用服务端 `HBK_PUBLIC_CENTER_URL` 和当前请求地址。若 agent 部署在其他主机或容器里，这里应填写它真正能访问到的中心地址。
                    </div>
                  </label>
                </div>

                <div className="rounded-[24px] bg-secondary/70 p-4 text-sm leading-7 text-slate-700">
                  当前表单会直接注册节点并生成 token，同时返回轻量 Agent 部署命令。节点注册后会立刻出现在左侧列表中，但在收到首次心跳前会显示为“异常”。
                </div>

                <div className="rounded-[24px] border border-primary/20 bg-white/80 p-4 text-sm leading-7 text-slate-700">
                  如果 agent 运行在另一台服务器或容器里，不要让生成命令里的 `--center-url` 或 `HBK_CENTER_URL` 指向 `127.0.0.1` / `localhost`。请在上面的“Agent 访问中心地址”里填写远端真正可达的中心地址。
                </div>

                {registrationError ? (
                  <div className="rounded-[24px] border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{registrationError}</div>
                ) : null}

                <div className="flex justify-end gap-3">
                  <Button type="button" variant="outline" onClick={resetRegisterModal}>
                    取消
                  </Button>
                  <Button type="submit" disabled={registering}>
                    <Plus className="h-4 w-4" />
                    {registering ? "注册中..." : "生成轻量 Agent 命令"}
                  </Button>
                </div>
              </form>
            ) : (
              <div className="space-y-5 overflow-y-auto p-6">
                <div className="rounded-[24px] border border-emerald-200 bg-emerald-50 p-4 text-sm leading-7 text-emerald-700">
                  节点 {registrationResult.node_name} 已注册成功。当前提供两套部署方式：
                  “方案 1：Python + systemd”和“方案 2：Docker Compose”。任选一种执行即可。
                </div>

                {copyMessage ? <div className="text-sm text-primary">{copyMessage}</div> : null}
                {isLocalCenterUrl ? (
                  <div className="rounded-[24px] border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-700">
                    当前生成的中心地址是 `{registrationResult.center_url}`。这个地址只适用于当前本机；如果 agent 部署在其他服务器或容器里，请返回上一步填写“Agent 访问中心地址”，或在后端配置 `HBK_PUBLIC_CENTER_URL` 后重新生成命令。
                  </div>
                ) : null}

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-[24px] border border-border/70 bg-secondary/60 p-4">
                    <div className="text-sm text-muted-foreground">节点 ID</div>
                    <div className="mt-2 text-lg font-semibold text-slate-900">{registrationResult.node_id}</div>
                  </div>
                  <div className="rounded-[24px] border border-border/70 bg-secondary/60 p-4">
                    <div className="text-sm text-muted-foreground">中心地址</div>
                    <div className="mt-2 text-lg font-semibold text-slate-900">{registrationResult.center_url}</div>
                  </div>
                </div>

                <CommandBlock title="节点 Token" value={registrationResult.token} onCopy={handleCopy} />

                <div className="rounded-[24px] border border-border/70 bg-white/70 p-4">
                  <div className="text-base font-semibold text-slate-900">部署方案切换</div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    每次只展示一套部署命令，避免两套方案混在一起。可以随时切换查看。
                  </p>
                  <div className="mt-4 flex flex-wrap gap-3">
                    <Button
                      variant={selectedInstallPlan === "python" ? "default" : "outline"}
                      onClick={() => setSelectedInstallPlan("python")}
                    >
                      方案 1：Python + systemd
                    </Button>
                    <Button
                      variant={selectedInstallPlan === "docker" ? "default" : "outline"}
                      onClick={() => setSelectedInstallPlan("docker")}
                    >
                      方案 2：Docker Compose
                    </Button>
                  </div>
                </div>

                {selectedInstallPlan === "python" ? (
                  <>
                    <div className="rounded-[24px] border border-border/70 bg-white/70 p-4">
                      <div className="text-base font-semibold text-slate-900">方案 1：Python + systemd</div>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        适合直接把 Agent 作为宿主机进程运行。初始化命令只安装 `requirements-agent.txt` 中的轻量依赖，不会带上中心端 FastAPI 和测试依赖。
                      </p>
                    </div>

                    <CommandBlock
                      title="GitHub 拉取命令"
                      value={githubCloneCommands}
                      onCopy={handleCopy}
                    />
                    <CommandBlock title="CentOS 初始化命令" value={registrationResult.commands.bootstrap_script} onCopy={handleCopy} />
                    <CommandBlock title="Agent 启动命令" value={registrationResult.commands.run_command} onCopy={handleCopy} />
                    <CommandBlock title="systemd 单元文件" value={registrationResult.commands.systemd_unit} onCopy={handleCopy} />
                    <CommandBlock
                      title="systemd 启用命令"
                      value={registrationResult.commands.systemd_enable_commands}
                      onCopy={handleCopy}
                    />
                  </>
                ) : (
                  <>
                    <div className="rounded-[24px] border border-border/70 bg-white/70 p-4">
                      <div className="text-base font-semibold text-slate-900">方案 2：Docker Compose</div>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        `Dockerfile.agent` 和 `docker-compose.agent.yml` 已经放在仓库里，镜像也只安装 `requirements-agent.txt` 中的轻量依赖。拉取代码后，只需要执行 `docker build` 和 `docker compose up` 即可启动。
                      </p>
                    </div>

                    <CommandBlock
                      title="GitHub 拉取命令"
                      value={githubCloneCommands}
                      onCopy={handleCopy}
                    />
                    <CommandBlock
                      title="Docker 构建命令"
                      value={registrationResult.commands.docker_build_command}
                      onCopy={handleCopy}
                    />
                    <CommandBlock
                      title="Docker Compose 启动命令"
                      value={registrationResult.commands.docker_compose_up_command}
                      onCopy={handleCopy}
                    />
                  </>
                )}

                <div className="flex justify-end gap-3">
                  <Button variant="outline" onClick={resetRegisterModal}>
                    关闭
                  </Button>
                </div>
              </div>
            )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
