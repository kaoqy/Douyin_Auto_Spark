# 抖音自动续火花管理面板

基于 FastAPI + SQLite + Playwright 的抖音自动续火花管理面板，支持多账号、多好友、定时任务、SOCKS 代理、随机一言等功能。

## 功能

- 🎭 **Cookie 登录** - 通过 Cookie-Editor 导出抖音 Cookie，无需账号密码
- 👥 **多账号管理** - 支持添加多个抖音账号
- 💬 **多好友续火** - 每个账号可配置多个续火好友
- 🎯 **随机一言** - 从内置一言库随机挑选消息发送
- ⏰ **定时续火** - 通过 APScheduler 定时自动续火
- 🔒 **SOCKS 代理** - 支持为账号配置 SOCKS5 代理
- 📊 **日志查看** - 查看续火历史日志
- 🌐 **Web 管理面板** - 简洁的 Web 界面管理所有配置

## 快速开始

### 方式一：Docker run（推荐）

```bash
# 拉取镜像
docker pull kaoqy666/douyin-auto-spark:latest

# 启动（替换为你的管理员密码）
docker run -d \
  --name douyin-auto-spark \
  -p 8000:8000 \
  -e DAS_ADMIN_USER=admin \
  -e DAS_ADMIN_PASSWORD=your_secure_password \
  -v douyin_data:/app/data \
  --restart unless-stopped \
  kaoqy666/douyin-auto-spark:latest

# 查看日志
docker logs -f douyin-auto-spark

# 访问 http://localhost:8000
```

### 方式二：Docker Compose

```bash
# 拉取镜像
docker pull kaoqy666/douyin-auto-spark:latest

# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 访问 http://localhost:8000
```

**docker-compose.yml：**

```yaml
services:
  das:
    image: kaoqy666/douyin-auto-spark:latest
    container_name: douyin-auto-spark
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - TZ=Asia/Shanghai
      - DAS_ADMIN_USER=admin
      - DAS_ADMIN_PASSWORD=your_secure_password
    volumes:
      - ./data:/app/data
```

### 方式三：本地部署

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 启动
python run.py --host 0.0.0.0 --port 8000

# 访问 http://localhost:8000
```

## 配置说明

首次访问 http://localhost:8000 会引导创建管理员账号。

### 添加账号

1. 使用 Chrome/Edge 安装 Cookie-Editor 插件
2. 打开 https://www.douyin.com/chat 并登录
3. 点击 Cookie-Editor → Export → JSON，复制内容
4. 在管理面板添加账号，粘贴 Cookie

### 配置好友

为每个账号配置需要续火的好友名称（建议使用抖音备注名）。

### 设置定时

在设置页面配置 Cron 表达式，如 `0 8 * * *`（每天 8 点）。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DAS_ADMIN_USER` | `admin` | 管理员用户名 |
| `DAS_ADMIN_PASSWORD` | `admin123` | 管理员密码 |
| `APP_HOST` | `0.0.0.0` | 监听地址 |
| `APP_PORT` | `8000` | 监听端口 |
| `DAS_DATA_DIR` | `./data` | 数据目录 |
| `PLAYWRIGHT_HEADLESS` | `1` | 无头模式 |
| `TZ` | `Asia/Shanghai` | 时区 |

## 项目结构

```
douyin-auto-spark/
├── app/
│   ├── api/          # API 路由
│   ├── static/       # 前端静态文件
│   ├── assets/       # 资源文件（一言库）
│   ├── database.py   # 数据库操作
│   ├── auth.py       # 认证
│   ├── douyin_runner.py  # Playwright 自动化
│   ├── scheduler.py  # 定时任务
│   ├── yiyan.py      # 一言管理
│   └── main.py       # FastAPI 入口
├── tests/            # 测试
├── data/             # 数据目录（SQLite）
├── Dockerfile
├── docker-compose.yml
├── run.py
└── requirements.txt
```
