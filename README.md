# wawayu-ai-service

`wawayu-ai-service` 是长期独立运行的统一 AI 能力服务，负责承载 AI 理解、抽取、分类、匹配、推理和工作流能力。业务事实仍由上游业务系统维护，本服务不作为业务后端使用。

当前提供基础健康检查和“招聘事件跟进”原型能力。招聘事件能力会调用配置的真实模型，但只返回待用户确认的候选事实，不直接读写业务数据库。

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

服务启动后提供以下接口：

```text
GET /health
POST /v1/capabilities/recruitment-event-follow-up/analyze
```

招聘事件接口使用 `X-AI-Service-Key` 做服务间鉴权，需要配置：

```text
AI_SERVICE_API_KEY=<long-random-value>
```

请求与响应示例、状态安全规则和校招雷达接入流程见 [招聘事件跟进能力接入指南](docs/recruitment-event-follow-up.md)。运行时 OpenAPI 位于 `/openapi.json`，交互文档位于 `/docs`。

浏览器演示页位于 `/demo/`。填写本地配置的 `AI_SERVICE_API_KEY` 后，可使用“填充测试数据”快速演示当前能力；该页面只用于本地或受控环境，不应暴露在公网。

## 运行测试

```bash
uv run pytest
```

## 代码检查

```bash
uv run ruff check .
```
