# HBK Panel

一个可本地运行的轻量监控集群示例：

- 中心节点：FastAPI
- 前端：React + Vite + shadcn/ui 风格组件
- 通信模型：`agent push` 为主，`center` 下发任务为辅
- 协议：HTTP/HTTPS + JSON

## 核心约束

- 心跳间隔：10~15 秒
- 离线判定：30~45 秒未收到心跳即标记异常
- 安全：`node_id + token + TLS`
- 可靠性：超时、重试、退避、幂等
- 数据语义：保留探测发起方
- 时间语义：同时保留节点采样时间和中心接收时间

## 目录结构

```text
HBK-Panel/
├─ backend/
│  ├─ app/
│  │  ├─ api/          # center / agent 接口
│  │  ├─ models/       # Pydantic 模型
│  │  └─ services/     # 中心状态管理、本机采集
│  └─ scripts/
│     └─ demo_agent.py # 本地模拟多节点 Agent
└─ frontend/           # React 页面
```

## 中心节点接口

- `GET /api/health`
- `POST /api/center/nodes/register`
- `GET /api/center/nodes`
- `GET /api/center/nodes/{node_id}`
- `GET /api/center/nodes/{node_id}/metrics`
- `GET /api/center/nodes/{node_id}/containers`
- `POST /api/center/nodes/{node_id}/tasks`
- `POST /api/center/nodes/{node_id}/clear-state`
- `DELETE /api/center/nodes/{node_id}`

## Agent 接口

- `POST /api/agent/heartbeat`
- `GET /api/agent/tasks/pull`
- `POST /api/agent/tasks/{task_id}/ack`

## 前端节点操作

前端右上角提供“新增节点”按钮，当前支持三类操作：

1. 新增节点
   - 输入 `node_id`、节点名称、地址提示和安装目录
   - 调用 `POST /api/center/nodes/register`
   - 返回 token、GitHub 拉取命令、CentOS 初始化命令、Agent 启动命令、`systemd` 模板，以及 Docker 方案的 `docker build` / `docker compose up` 命令
   - `Dockerfile.agent` 和 `docker-compose.agent.yml` 直接放在仓库根目录，不需要在目标主机手工创建

2. 清理状态
   - 调用 `POST /api/center/nodes/{node_id}/clear-state`
   - 只清掉中心内存中的运行态缓存
   - 不删除注册信息，不废掉 token
   - Agent 下一次心跳后节点会重新出现

3. 注销节点
   - 调用 `DELETE /api/center/nodes/{node_id}`
   - 从中心注册表移除节点并立即废掉 token
   - 之后该 Agent 再发心跳会直接返回 `401`
   - 如果该节点来自启动配置，中心重启后且配置未改，它仍会重新出现

## 最简启动说明

第一次启动，先各装一次依赖：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd ..\frontend
npm install
```

之后日常启动，开 3 个终端就够了：

1. 启动后端

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

2. 启动前端

```powershell
cd frontend
npm run dev
```

3. 启动一个 demo agent（可选，但不启动就看不到在线节点数据）

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\demo_agent.py --node-id node-a --token token-node-a-demo --node-name "华东-节点-A" --auto-ack
```

启动后直接访问：

- 前端：`http://127.0.0.1:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`

## 本地启动

### 1. 安装后端依赖

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 启动中心节点

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 3. 启动两个 demo agent

默认内置了三个 demo 节点 token：

- `node-a -> token-node-a-demo`
- `node-b -> token-node-b-demo`
- `node-c -> token-node-c-demo`

示例命令：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\demo_agent.py --node-id node-a --token token-node-a-demo --node-name "华东-节点-A" --auto-ack
.\.venv\Scripts\python.exe scripts\demo_agent.py --node-id node-b --token token-node-b-demo --node-name "华北-节点-B" --auto-ack
```

### 4. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认前端访问 `http://127.0.0.1:8000`，如需修改：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
```

## 测试与构建

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest

cd ..\frontend
npm run build
```

## 说明

- 当前中心节点使用内存态注册表，适合轻量示例和本地联调
- 生产环境建议启用 `HBK_REQUIRE_TLS=true` 并将服务置于 HTTPS 入口后
- 如节点未安装 Docker，Agent 会把容器运行时不可用原因一并上报给中心
