# 招聘事件跟进能力接入指南

## 能力边界

该能力用于理解一条招聘邮件、短信、电话记录或招聘平台通知，并将其中的公司、岗位、招聘阶段、日程、截止时间和下一步事项整理成**待确认的候选变更**。

AI 服务是无状态的：

- 不接收平台用户 Token 或 `userId`；
- 不回查校招雷达或统一平台数据库；
- 不保存通知正文、投递状态或对话记忆；
- 不直接修改投递阶段、时间线或待办；
- 只允许匹配调用方本次请求提供的候选投递。

当前 `CampusRecruitmentRadar` 的个人投递状态仍保存在浏览器 localStorage；`wawayu-platform` 已有收藏、投递、事件和待办表结构，但尚未实现完整的 C 端个人业务接口。因此本接口是可独立验证的 AI 能力，下面的业务接入链路是后续接入约定，不代表两个仓库已经完成集成。

## 调用接口

```text
POST /v1/capabilities/recruitment-event-follow-up/analyze
Content-Type: application/json
X-AI-Service-Key: <server-to-server-secret>
```

`X-AI-Service-Key` 只应保存在 Java 服务或其他可信服务端，不能下发到浏览器。未配置服务端密钥时接口返回 503；缺失或错误密钥返回 401。

### 请求示例

```json
{
  "source": {
    "channel": "EMAIL",
    "subject": "字节跳动在线测评通知",
    "content": "你申请的后端开发工程师岗位已进入在线测评环节，请在2026年9月10日18:00前完成测评。",
    "receivedAt": "2026-09-06T10:00:00+08:00"
  },
  "timezone": "Asia/Shanghai",
  "candidates": [
    {
      "applicationId": "application-1024",
      "applicationVersion": 3,
      "jobCode": "job-001",
      "companyName": "北京字节跳动科技有限公司",
      "companyAliases": ["字节跳动", "字节"],
      "jobTitle": "后端开发工程师",
      "currentStage": "APPLIED"
    }
  ]
}
```

请求约束：

- 一次只分析一条纯文本通知；`content` 最长 20,000 字符。
- `receivedAt` 必须包含时区偏移，不能传无时区的本地时间。
- `timezone` 必须是有效 IANA 时区，缺省为 `Asia/Shanghai`。
- `candidates` 必须包含 1–30 条当前用户的真实投递，`applicationId` 不得重复。
- `channel` 支持 `EMAIL`、`SMS`、`PHONE_NOTE`、`RECRUITMENT_PLATFORM`、`OTHER`。
- `currentStage` 支持 `APPLIED`、`ASSESSMENT`、`INTERVIEW`、`OFFER`、`REJECTED`、`WITHDRAWN`。

建议 Java 服务先用通知中的发件域、公司名或已有岗位信息做轻量筛选，只发送少量可能相关的投递。不要把用户全部历史信息或其他用户数据交给模型。

### 响应示例

```json
{
  "analysisId": "b0d58b9e-cd67-4237-9d59-a5cd1758709e",
  "sourceFingerprint": "24f284eb91d5c1feec0654d229d98a54431cb0c0a6b70e82bb03720872d83b43",
  "match": {
    "status": "MATCHED",
    "selected": {
      "applicationId": "application-1024",
      "jobCode": "job-001",
      "confidence": "HIGH",
      "evidence": "字节跳动在线测评通知"
    },
    "candidates": [
      {
        "applicationId": "application-1024",
        "jobCode": "job-001",
        "confidence": "HIGH",
        "evidence": "字节跳动在线测评通知"
      }
    ]
  },
  "facts": {
    "companyName": {
      "value": "字节跳动",
      "confidence": "HIGH",
      "evidence": "字节跳动"
    },
    "jobTitle": {
      "value": "后端开发工程师",
      "confidence": "HIGH",
      "evidence": "后端开发工程师"
    },
    "eventType": {
      "value": "ASSESSMENT",
      "confidence": "HIGH",
      "evidence": "在线测评"
    },
    "recruitmentStage": {
      "value": "ASSESSMENT",
      "confidence": "HIGH",
      "evidence": "在线测评环节"
    },
    "scheduledAt": {
      "value": null,
      "confidence": "LOW",
      "evidence": null,
      "inferred": false
    },
    "deadlineAt": {
      "value": "2026-09-10T18:00:00+08:00",
      "confidence": "HIGH",
      "evidence": "2026年9月10日18:00前",
      "inferred": false
    },
    "nextAction": {
      "value": {
        "taskType": "ASSESSMENT",
        "title": "完成字节跳动在线测评",
        "dueAt": "2026-09-10T18:00:00+08:00"
      },
      "confidence": "HIGH",
      "evidence": "请在2026年9月10日18:00前完成测评"
    },
    "summary": "收到字节跳动在线测评通知，需在 9 月 10 日 18:00 前完成。"
  },
  "proposedChange": {
    "applicationId": "application-1024",
    "expectedVersion": 3,
    "jobCode": "job-001",
    "stageChange": {
      "fromStage": "APPLIED",
      "toStage": "ASSESSMENT"
    },
    "timelineEvent": {
      "eventType": "STAGE_CHANGE",
      "occurredAt": "2026-09-06T10:00:00+08:00",
      "fromStage": "APPLIED",
      "toStage": "ASSESSMENT",
      "note": "收到字节跳动在线测评通知，需在 9 月 10 日 18:00 前完成。"
    },
    "task": {
      "taskType": "ASSESSMENT",
      "title": "完成字节跳动在线测评",
      "dueAt": "2026-09-10T18:00:00+08:00",
      "remindAt": null
    }
  },
  "requiresConfirmation": true,
  "warnings": []
}
```

`facts` 中每个关键字段都有置信度和原文证据。服务会删除无法在原通知中找到的伪造证据，并在 `warnings` 中说明。相对时间和缺少年份的时间会依据 `receivedAt + timezone` 归一化，并标记 `inferred=true`；不能唯一确定时返回 `value=null`。

## 匹配和确认规则

`match.status` 的处理方式：

| 状态 | 含义 | 调用方处理 |
| --- | --- | --- |
| `MATCHED` | 唯一候选投递 | 展示候选事实与 `proposedChange`，等待用户确认 |
| `AMBIGUOUS` | 多个候选都可能匹配 | 让用户先选择岗位；不能直接落库 |
| `UNMATCHED` | 没有可信候选 | 展示已抽取事实并让用户手动处理；不能新建投递 |

即使 `confidence=HIGH`，`requiresConfirmation` 仍固定为 `true`。调用方不得把 HTTP 200 或高置信度解释为已经确认。

确定性状态保护包括：

- 禁止 `APPLIED → ASSESSMENT → INTERVIEW → OFFER` 的倒退覆盖；
- `REJECTED` 可以从非终态提出，Offer 后的拒绝必须人工处理；
- AI 永不提出 `WITHDRAWN`；
- 当前为 `REJECTED/WITHDRAWN` 时不再提出阶段变更；
- 日程和截止时间均早于分析时间时标记为疑似旧通知，不产生阶段变更和过期待办；
- 没有可用截止时间的下一步事项不生成业务待办。

`warnings` 当前可能包含：

- `MODEL_RETURNED_UNKNOWN_APPLICATION_ID`
- `EVIDENCE_NOT_FOUND_IN_SOURCE`
- `NOTIFICATION_APPEARS_STALE`
- `WITHDRAWN_REQUIRES_USER_ACTION`
- `CURRENT_STAGE_IS_TERMINAL`
- `OFFER_REJECTION_REQUIRES_MANUAL_REVIEW`
- `STAGE_REGRESSION_SUPPRESSED`
- `NEXT_ACTION_WITHOUT_DUE_AT`
- `PAST_DUE_TASK_SUPPRESSED`
- `EVENT_STAGE_CONFLICT_RESOLVED`
- `NEXT_ACTION_CONFLICTS_WITH_EVENT`

调用方应容忍新增 warning 值，不要把它实现成封闭枚举。

## 推荐业务接入链路

后续推荐把面向浏览器的接口放在现有 `/v1/me/applications/**` 个人业务边界内：

1. 校招雷达把用户粘贴的通知提交到自身 `/api/business/**` BFF，不直接调用 AI 服务。
2. Java 服务使用 Platform Token 确认当前用户，再查询该用户的候选投递及版本号。
3. Java 服务仅携带本次需要的候选上下文，使用内部密钥调用本接口。
4. 校招雷达展示匹配结果、字段证据、警告、阶段变化和待办草稿。
5. 用户确认后，Java 服务重新校验投递版本，用 `expectedVersion` 做乐观锁，并将阶段事件以不可变追加方式写入。
6. Java 服务在用户维度使用 `sourceFingerprint` 做幂等；该指纹由规范化后的渠道、标题、正文和接收时间生成。同一通知重复提交时返回已经存在的确认结果，而不是重复新增事件和待办。

模型负责理解本次信息，业务系统负责保存用户确认后的事实。后续调用只需要提供当前投递状态和本次候选岗位，不需要把全部历史通知重新放入模型上下文。

## 错误处理

| HTTP 状态 | `detail.code` | 处理建议 |
| --- | --- | --- |
| 401 | `INVALID_AI_SERVICE_KEY` | 检查服务间密钥，不要重试错误凭据 |
| 422 | FastAPI 校验详情 | 修正请求字段、时区、候选数量或时间格式 |
| 502 | `AI_PROVIDER_ERROR` | 模型服务失败或结构化结果无效；可有限重试 |
| 503 | `AI_SERVICE_KEY_NOT_CONFIGURED` / `AI_PROVIDER_NOT_CONFIGURED` / `AI_PROVIDER_AUTHENTICATION_ERROR` | 修复 AI 服务或模型凭据配置后重试 |
| 504 | `AI_PROVIDER_TIMEOUT` | 使用相同业务幂等上下文有限重试 |

调用方不应在错误日志中记录完整通知正文。`analysisId` 可用于单次分析链路追踪，`sourceFingerprint` 用于用户业务范围内的通知去重，两者都不能代替用户确认。

## 本地调用

启动服务后可以访问 `http://127.0.0.1:8000/demo/` 打开最小演示页。点击“填充测试数据”，填写本地 `.env` 中的 `AI_SERVICE_API_KEY`，再点击“开始 AI 识别”即可展示匹配、事实、证据、建议阶段和待办草稿。演示页会在当前请求中使用密钥，但不会把密钥写入 localStorage 或 sessionStorage；它只应运行在本地或受控网络中。

也可以使用 curl：

```bash
curl -X POST 'http://127.0.0.1:8000/v1/capabilities/recruitment-event-follow-up/analyze' \
  -H 'Content-Type: application/json' \
  -H 'X-AI-Service-Key: local-development-key' \
  --data-binary @request.json
```

运行所需配置见仓库 `.env.example`。自动测试使用假分析器，不访问外部模型；真实模型冒烟测试应在本地显式执行，且不要提交密钥或包含真实个人信息的通知样本。
