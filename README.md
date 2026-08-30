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

### Docker 部署

```bash
# 克隆项目
git clone https://github.com/kaoqy/douyin-auto-spark.git
cd douyin-auto-spark

# 启动
docker compose up -d

# 访问 http://localhost:8000
```

### 本地部署

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 启动
python run.py --host 0.0.0.0 --port 8000
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
