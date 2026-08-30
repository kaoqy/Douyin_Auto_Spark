# 抖音自动续火花管理面板 - Makefile
.PHONY: help install test run build deploy clean

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/playwright install chromium

test: ## 运行测试
	.venv/bin/python -m pytest tests/ -v

run: ## 启动 Web 面板
	.venv/bin/python run.py --host 0.0.0.0 --port 8000

spark: ## 执行一次续火任务
	.venv/bin/python run.py --spark

build: ## 构建 Docker 镜像
	docker compose build

deploy: ## 启动 Docker 部署
	docker compose up -d

clean: ## 清理
	rm -rf .venv .pytest_cache __pycache__ */__pycache__ data/
