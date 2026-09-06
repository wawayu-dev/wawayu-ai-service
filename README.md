# wawayu-ai-service

`wawayu-ai-service` 是长期独立运行的统一 AI 能力服务，负责承载 AI 理解、抽取、分类、匹配、推理和工作流能力。业务事实仍由上游业务系统维护，本服务不作为业务后端使用。

当前阶段仅包含基础工程框架和健康检查接口，不包含具体 AI 业务能力，也不会调用真实大模型。

## 环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## 安装依赖

```bash
uv sync
```

如需配置本地环境变量，可复制示例文件并按需修改：

```bash
cp .env.example .env
```

## 启动服务

```bash
uv run uvicorn app.main:app --reload
```

服务启动后，唯一的接口为：

```text
GET /health
```

## 运行测试

```bash
uv run pytest
```

## 代码检查

```bash
uv run ruff check .
```
