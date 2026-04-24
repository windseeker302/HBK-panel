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
├─ deploy/nginx/        # Docker 前端反代配置
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
   - Agent 安装命令只使用 `backend/requirements-agent.txt`，不会额外安装中心端 FastAPI、Uvicorn 和测试依赖

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

## 中心端 Docker 部署

当前仓库除了 `Dockerfile.agent` / `docker-compose.agent.yml` 之外，又补了一套中心端部署文件：

- `Dockerfile.server`：构建 FastAPI 中心节点镜像
- `Dockerfile.frontend`：构建 React 前端并用 Nginx 托管
- `docker-compose.server.yml`：一条命令启动中心端前后端
- `deploy/nginx/hbk-panel.conf`：前端静态资源和 `/api` 反向代理配置
- `.env.server.example`：中心端部署环境变量示例

推荐在服务器上这样启动：

```bash
git clone https://github.com/windseeker302/HBK-panel.git
cd HBK-Panel
cp .env.server.example .env
```

然后编辑 `.env`，至少改这两个值：

- `HBK_PUBLIC_CENTER_URL`
  - 填 Agent 真正可访问到的中心地址
  - 例如 `http://10.20.30.40`
  - 如果你把 `HBK_SERVER_PORT` 改成了 `8080`，这里也要写成 `http://10.20.30.40:8080`
- `HBK_SERVER_PORT`
  - 前端和 `/api` 对外暴露的端口，默认 `80`

如果这台服务器拉不到 Docker Hub，还可以把基础镜像改成你能访问到的镜像仓库地址：

- `HBK_PYTHON_BASE_IMAGE`
- `HBK_NODE_BASE_IMAGE`
- `HBK_NGINX_BASE_IMAGE`

默认值分别是：

```env
HBK_PYTHON_BASE_IMAGE=python:3.11-slim
HBK_NODE_BASE_IMAGE=node:20-alpine
HBK_NGINX_BASE_IMAGE=nginx:1.27-alpine
```

例如你已经有私有镜像仓库或云厂商镜像仓库时，可以直接改成完整镜像名；这样 `docker compose build` 时就不会再去访问默认的 Docker Hub 地址。

启动命令：

```bash
docker compose -f docker-compose.server.yml up -d --build
```

启动后访问：

- 前端：`http://<你的服务器IP或域名>`
- 后端健康检查：`http://<你的服务器IP或域名>/api/health`

常用排查命令：

```bash
docker compose -f docker-compose.server.yml ps
docker compose -f docker-compose.server.yml logs -f backend
docker compose -f docker-compose.server.yml logs -f frontend
```

说明：

- 这套中心端 Docker 部署把前端和后端放到同一个入口上，前端页面访问 `/api/*` 时由 Nginx 反代到 FastAPI。
- 因为 Agent 也访问同一个 `/api/agent/*`，所以 `HBK_PUBLIC_CENTER_URL` 一般应该写成前端对外入口地址，而不是容器内部的 `backend:8000`。
- 如果你通过 HTTPS 反向代理暴露这个面板，建议同时设置 `HBK_REQUIRE_TLS=true`。

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
- 当前运行时注册的节点和 token 只保存在内存里，中心容器重启后会丢失；如果要保留固定节点，请在启动前配置 `HBK_NODE_TOKENS_JSON`
