const form = document.querySelector("#analysis-form");
const fillDemoButton = document.querySelector("#fill-demo");
const analyzeButton = document.querySelector("#analyze-button");
const requestStatus = document.querySelector("#request-status");
const resultPanel = document.querySelector("#result-panel");
const matchBadge = document.querySelector("#match-badge");
const matchSummary = document.querySelector("#match-summary");
const factsGrid = document.querySelector("#facts-grid");
const proposedChange = document.querySelector("#proposed-change");
const warningsBlock = document.querySelector("#warnings-block");
const warningsList = document.querySelector("#warnings-list");
const rawJson = document.querySelector("#raw-json");

const stageLabels = {
  APPLIED: "已投递",
  ASSESSMENT: "测评 / 笔试",
  INTERVIEW: "面试",
  OFFER: "Offer",
  REJECTED: "已拒绝",
  WITHDRAWN: "已放弃",
};

const eventLabels = {
  APPLICATION_ACKNOWLEDGED: "投递确认",
  ASSESSMENT: "测评 / 笔试",
  INTERVIEW: "面试",
  OFFER: "Offer",
  REJECTION: "拒绝",
  MATERIAL_REQUEST: "材料提交",
  OTHER: "其他通知",
};

const confidenceLabels = { HIGH: "高", MEDIUM: "中", LOW: "低" };

function byId(id) {
  return document.getElementById(id);
}

function localInputValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function shanghaiDateParts(date) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(date);
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

fillDemoButton.addEventListener("click", () => {
  const now = new Date();
  const deadline = new Date(now.getTime() + 3 * 24 * 60 * 60 * 1000);
  const date = shanghaiDateParts(deadline);

  byId("channel").value = "EMAIL";
  byId("received-at").value = localInputValue(now);
  byId("subject").value = "示例科技在线测评通知";
  byId("content").value =
    `你申请的后端开发工程师岗位已进入在线测评环节，` +
    `请在${date.year}年${date.month}月${date.day}日18:00前完成测评。`;
  byId("company-name").value = "示例科技有限公司";
  byId("company-aliases").value = "示例科技, 示例公司";
  byId("job-title").value = "后端开发工程师";
  byId("current-stage").value = "APPLIED";
  byId("application-id").value = "demo-application-001";
  byId("job-code").value = "demo-job-001";
  requestStatus.className = "";
  requestStatus.textContent = "测试数据已填充，请填写内部测试密钥后开始识别。";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const serviceKey = byId("service-key").value.trim();
  if (!serviceKey) {
    setRequestStatus("请先填写 AI_SERVICE_API_KEY。", true);
    return;
  }

  analyzeButton.disabled = true;
  setRequestStatus("正在调用模型分析，请稍候……");
  resultPanel.hidden = true;

  try {
    const response = await fetch(
      "/v1/capabilities/recruitment-event-follow-up/analyze",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-AI-Service-Key": serviceKey,
        },
        body: JSON.stringify(buildPayload()),
      },
    );
    const body = await response.json();
    if (!response.ok) {
      const detail = body.detail;
      const message =
        typeof detail === "object" && detail?.message
          ? `${detail.message} (${detail.code ?? response.status})`
          : `请求失败，HTTP ${response.status}`;
      throw new Error(message);
    }

    renderResult(body);
    setRequestStatus("识别完成。以下结果仍需用户确认。", false);
  } catch (error) {
    setRequestStatus(error instanceof Error ? error.message : "请求失败。", true);
  } finally {
    analyzeButton.disabled = false;
  }
});

function buildPayload() {
  const receivedAt = new Date(byId("received-at").value);
  return {
    source: {
      channel: byId("channel").value,
      subject: byId("subject").value.trim() || null,
      content: byId("content").value.trim(),
      receivedAt: receivedAt.toISOString(),
    },
    timezone: "Asia/Shanghai",
    candidates: [
      {
        applicationId: byId("application-id").value.trim(),
        applicationVersion: 1,
        jobCode: byId("job-code").value.trim(),
        companyName: byId("company-name").value.trim(),
        companyAliases: byId("company-aliases")
          .value.split(/[,，]/)
          .map((value) => value.trim())
          .filter(Boolean),
        jobTitle: byId("job-title").value.trim(),
        currentStage: byId("current-stage").value,
      },
    ],
  };
}

function renderResult(result) {
  resultPanel.hidden = false;
  const status = result.match.status;
  matchBadge.className = `badge ${status.toLowerCase()}`;
  matchBadge.textContent = status;

  const selected = result.match.selected;
  matchSummary.textContent = selected
    ? `唯一匹配：${selected.jobCode} / ${selected.applicationId}，匹配置信度：${confidenceLabels[selected.confidence] ?? selected.confidence}`
    : status === "AMBIGUOUS"
      ? `检测到 ${result.match.candidates.length} 个可能岗位，需要用户选择。`
      : "未匹配到现有投递，不会生成可落库变更。";

  factsGrid.replaceChildren(
    factCard("公司", result.facts.companyName),
    factCard("岗位", result.facts.jobTitle),
    factCard("招聘事件", result.facts.eventType, eventLabels),
    factCard("建议阶段", result.facts.recruitmentStage, stageLabels),
    factCard("测评 / 面试时间", result.facts.scheduledAt, null, true),
    factCard("截止时间", result.facts.deadlineAt, null, true),
    factCard("下一步事项", result.facts.nextAction),
    summaryCard(result.facts.summary),
  );

  renderProposedChange(result.proposedChange);
  renderWarnings(result.warnings);
  rawJson.textContent = JSON.stringify(result, null, 2);
  resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function factCard(label, fact, labels = null, isDate = false) {
  const card = document.createElement("article");
  card.className = "fact-card";

  const labelElement = document.createElement("p");
  labelElement.className = "fact-label";
  labelElement.textContent = label;

  const valueElement = document.createElement("p");
  valueElement.className = "fact-value";
  valueElement.textContent = displayFactValue(fact?.value, labels, isDate);
  const confidence = document.createElement("span");
  confidence.className = "confidence";
  confidence.textContent = `置信度：${confidenceLabels[fact?.confidence] ?? "-"}`;
  valueElement.append(confidence);

  const evidence = document.createElement("p");
  evidence.className = "evidence";
  evidence.textContent = fact?.evidence
    ? `原文：“${fact.evidence}”${fact.inferred ? " · 时间含推断" : ""}`
    : "原文证据：无";

  card.append(labelElement, valueElement, evidence);
  return card;
}

function summaryCard(summary) {
  const card = document.createElement("article");
  card.className = "fact-card";
  const label = document.createElement("p");
  label.className = "fact-label";
  label.textContent = "事件摘要";
  const value = document.createElement("p");
  value.className = "fact-value";
  value.textContent = summary || "未生成摘要";
  card.append(label, value);
  return card;
}

function displayFactValue(value, labels, isDate) {
  if (value === null || value === undefined) return "未识别";
  if (isDate) return new Date(value).toLocaleString("zh-CN", { hour12: false });
  if (typeof value === "object") {
    const due = value.dueAt
      ? ` · ${new Date(value.dueAt).toLocaleString("zh-CN", { hour12: false })}`
      : "";
    return `${value.title}${due}`;
  }
  return labels?.[value] ?? value;
}

function renderProposedChange(change) {
  proposedChange.replaceChildren();
  if (!change) {
    proposedChange.append(textParagraph("当前没有可确认的业务变更。"));
    return;
  }

  if (change.stageChange) {
    proposedChange.append(
      textParagraph(
        `阶段：${stageLabels[change.stageChange.fromStage]} → ${stageLabels[change.stageChange.toStage]}`,
      ),
    );
  } else {
    proposedChange.append(textParagraph("阶段：保持当前状态"));
  }

  proposedChange.append(textParagraph(`时间线：${change.timelineEvent.note}`));
  proposedChange.append(
    textParagraph(
      change.task
        ? `待办：${change.task.title} · ${new Date(change.task.dueAt).toLocaleString("zh-CN", { hour12: false })}`
        : "待办：无",
    ),
  );
  proposedChange.append(
    textParagraph(`需要确认：是 · 预期数据版本：${change.expectedVersion}`),
  );
}

function renderWarnings(warnings) {
  warningsList.replaceChildren();
  warningsBlock.hidden = warnings.length === 0;
  for (const warning of warnings) {
    const item = document.createElement("li");
    item.textContent = warning;
    warningsList.append(item);
  }
}

function textParagraph(text) {
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  return paragraph;
}

function setRequestStatus(message, isError = false) {
  requestStatus.className = isError ? "error" : "";
  requestStatus.textContent = message;
}
