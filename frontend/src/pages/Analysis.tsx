import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  ChartNoAxesCombined,
  Upload,
  Trash2,
  FileText,
  Download,
  Settings2,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import {
  api,
  json,
  saveText,
  type Analysis as AnalysisResult,
  type DataSet,
  type Project,
  type DocumentInfo,
  type ProjectModelSettings,
} from "../api";
import { Button, Empty, Modal, Notice, useAction } from "../components/Common";
import { ScopeFields, initialScope } from "../components/ScopeFields";
import { DigitalTwinPanel } from "../components/DigitalTwinPanel";
export function AnalysisTable({ result }: { result: AnalysisResult }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((r, i) => (
            <tr key={i}>
              {result.columns.map((c) => (
                <td key={c}>{r[c] ?? "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Trends({ result }: { result: AnalysisResult }) {
  const [hidden, setHidden] = useState<string[]>([]);
  const units = Array.from(new Set(result.series.map((s) => s.unit)));
  return (
    <>
      {units.map((unit) => {
        const series = result.series.filter((s) => s.unit === unit),
          dates = Array.from(
            new Set(series.flatMap((s) => s.values.map((v) => v.date))),
          ).sort();
        const chart = dates.map((date) =>
          Object.fromEntries([
            ["date", date],
            ...series.map((s, i) => [
              "s" + i,
              s.values.find((v) => v.date === date)?.value ?? null,
            ]),
          ]),
        );
        return (
          <div className="chart-group" key={unit}>
            <h3>
              累计变化趋势 <small>单位：{unit}</small>
            </h3>
            <div className="series-picker">
              {series.map((s, i) => {
                const id = unit + i;
                return (
                  <label key={id}>
                    <input
                      type="checkbox"
                      checked={!hidden.includes(id)}
                      onChange={(e) =>
                        setHidden(
                          e.target.checked
                            ? hidden.filter((h) => h !== id)
                            : [...hidden, id],
                        )
                      }
                    />
                    {s.measurement_name ? s.measurement_name + " · " : ""}
                    {s.point}
                  </label>
                );
              })}
            </div>
            <div className="chart">
              <ResponsiveContainer width="100%" height={260}>
                <LineChart
                  data={chart}
                  margin={{ left: 6, right: 20, top: 14, bottom: 10 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  {series.map(
                    (s, i) =>
                      !hidden.includes(unit + i) && (
                        <Line
                          key={i}
                          type="linear"
                          connectNulls={false}
                          dataKey={"s" + i}
                          name={s.point}
                          stroke={
                            ["#167f80", "#3979d4", "#d99541", "#9772bf"][i % 4]
                          }
                          dot={{ r: 3 }}
                          strokeWidth={2}
                        />
                      ),
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })}
    </>
  );
}
export function Analysis({
  project,
  data,
}: {
  project: Project;
  data: DataSet;
}) {
  const [scope, setScope] = useState(initialScope(data)),
    [mode, setMode] = useState("hybrid"),
    [question, setQuestion] = useState(""),
    [result, setResult] = useState<AnalysisResult | null>(null),
    [answer, setAnswer] = useState<any>(null),
    [docsOpen, setDocsOpen] = useState(false),
    [modelOpen, setModelOpen] = useState(false),
    [modelDraft, setModelDraft] = useState({
      base_url: "",
      model: "",
      timeout: 90,
      api_key: "",
      clear_api_key: false,
    });
  const action = useAction(),
    upload = useAction(),
    modelAction = useAction(),
    cache = useQueryClient(),
    base = "/projects/" + project.id;
  const docs = useQuery({
    queryKey: ["documents", project.id],
    queryFn: () =>
      api<{
        documents: DocumentInfo[];
        model_configured: boolean;
        model: string;
      }>(base + "/documents"),
  });
  const modelSettings = useQuery<ProjectModelSettings>({
    queryKey: ["model-settings", project.id, project.revision],
    queryFn: () => api<ProjectModelSettings>(base + "/model-settings"),
  });
  function openModelSettings() {
    const current = modelSettings.data;
    setModelDraft({
      base_url: current?.base_url || "",
      model: current?.model || "",
      timeout: current?.timeout || 90,
      api_key: "",
      clear_api_key: false,
    });
    modelAction.clearStatus();
    setModelOpen(true);
  }
  function saveModelSettings() {
    modelAction.run(async () => {
      const current = (await modelSettings.refetch()).data;
      if (!current) throw new Error("模型设置尚未加载，请刷新后重试");
      await api(base + "/model-settings", {
        method: "PUT",
        body: JSON.stringify({
          revision: current.revision,
          base_url: modelDraft.base_url,
          model: modelDraft.model,
          timeout: modelDraft.timeout,
          ...(modelDraft.api_key ? { api_key: modelDraft.api_key } : {}),
          clear_api_key: modelDraft.clear_api_key,
        }),
      });
      await cache.invalidateQueries({
        queryKey: ["model-settings", project.id],
      });
      await cache.invalidateQueries({ queryKey: ["documents", project.id] });
      await cache.invalidateQueries({ queryKey: ["project", project.id] });
    }, "工程模型设置已保存");
  }
  const hasDocs = docs.data?.documents.some((d) => d.chunk_count > 0);
  const effectiveMode = mode === "documents" && !hasDocs ? "data" : mode;
  return (
    <>
      <DigitalTwinPanel
        project={project}
        data={data}
        scope={scope}
        setScope={setScope}
      />
      <div className="analysis-layout">
        <section className="analysis-main">
          <div className="panel">
            <div className="panel-heading">
              <div>
                <h2>
                  <Sparkles size={20} />
                  智能问答
                </h2>
                <p>结合当前工程资料与原始监测数据，生成有依据的分析草稿。</p>
              </div>
              <div className="analysis-heading-actions">
                <Button onClick={openModelSettings}>
                  <Settings2 size={16} />
                  模型设置
                </Button>
                <Button onClick={() => setDocsOpen(true)}>
                  <FileText size={16} />
                  项目资料{" "}
                  <span className="count">
                    {docs.data?.documents.length || 0}
                  </span>
                </Button>
              </div>
            </div>
            <Notice>{action.error || docs.error?.message}</Notice>
            {!docs.data?.model_configured && (
              <div className="info-note">
                尚未配置 AI
                模型。请点击“模型设置”填写本工程的云端或本地模型；监测数据计算仍可直接使用。
              </div>
            )}
            <textarea
              aria-label="分析问题"
              className="question-input"
              maxLength={4000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="例如：分析所选期间各点位的变化，列出异常情况与需要复核的事项。"
            />
            <div className="toolbar">
              <small className="muted">
                资料片段和所选数据会发送至管理员配置的模型服务。
              </small>
              <Button
                kind="primary"
                busy={action.busy}
                disabled={!question.trim()}
                onClick={() =>
                  action.run(async () => {
                    setAnswer(null);
                    const next = await api(
                      base + "/ask",
                      json({ ...scope, question, mode: effectiveMode }),
                    );
                    setAnswer(next);
                    if (next.analysis) setResult(next.analysis);
                  })
                }
              >
                <Sparkles size={16} />
                AI 回答
              </Button>
            </div>
            <div className="answer-grid">
              <section>
                <h3>思考过程</h3>
                <div className="answer-text muted">
                  {answer?.reasoning ||
                    "仅显示模型接口返回的思考内容；模型未返回时此处留空。"}
                </div>
              </section>
              <section>
                <div className="row-between">
                  <h3>结论</h3>
                  {answer && (
                    <button
                      className="text-button"
                      onClick={() =>
                        saveText(answer.answer, project.name + "-分析草稿.md")
                      }
                    >
                      导出草稿
                    </button>
                  )}
                </div>
                <textarea
                  aria-label="结论"
                  value={answer?.answer || ""}
                  placeholder="AI 结论将在这里显示，可编辑后导出。"
                  onChange={(e) =>
                    setAnswer({ ...answer, answer: e.target.value })
                  }
                />
              </section>
            </div>
            {answer?.warnings?.length > 0 && (
              <Notice>{answer.warnings.join("；")}</Notice>
            )}
            {answer?.sources?.length > 0 && (
              <div className="sources">
                <h3>引用依据</h3>
                {answer.sources.map((s: any) => (
                  <details key={s.id}>
                    <summary>
                      [{s.citation}] {s.name} · {s.location}
                    </summary>
                    <p>{s.text}</p>
                  </details>
                ))}
              </div>
            )}
          </div>
          <div className="panel">
            <div className="panel-heading">
              <div>
                <h2>
                  <ChartNoAxesCombined size={20} />
                  监测数据分析
                </h2>
                <p>计算过程沿用 V1.07 桌面版，保留缺测和阈值未配置提示。</p>
              </div>
            </div>
            {result ? (
              <>
                <Trends result={result} />
                <Notice>{result.warnings.join("；")}</Notice>
                <AnalysisTable result={result} />
              </>
            ) : (
              <Empty title="查看数据随时间的变化">
                在右侧选择测项和日期，点击“计算分析”。
              </Empty>
            )}
          </div>
        </section>
        <aside className="panel scope-panel">
          <h2>分析范围</h2>
          <ScopeFields data={data} scope={scope} setScope={setScope} />
          <label className="field">
            <span>问答范围</span>
            <select
              value={effectiveMode}
              onChange={(e) => setMode(e.target.value)}
            >
              <option value="hybrid">资料 + 监测数据</option>
              <option value="data">仅监测数据</option>
              <option value="documents" disabled={!hasDocs}>
                仅项目资料{hasDocs ? "" : "（请先上传）"}
              </option>
            </select>
          </label>
          <Button
            kind="primary full"
            busy={action.busy}
            disabled={!data.catalog.length}
            onClick={() =>
              action.run(async () =>
                setResult(
                  await api<AnalysisResult>(base + "/analysis", json(scope)),
                ),
              )
            }
          >
            <ChartNoAxesCombined size={16} />
            计算分析
          </Button>
          <p className="muted scope-note">
            综合分析覆盖当前工程全部测项和点位。不同测项保留各自单位，按配置分别判断。
          </p>
          <div className="scope-model">
            <small>当前模型</small>
            <strong>{docs.data?.model || "尚未配置"}</strong>
          </div>
        </aside>
      </div>
      {docsOpen && (
        <Modal title="项目资料" onClose={() => setDocsOpen(false)}>
          <p className="muted">
            支持 TXT、MD、PDF、DOCX、XLSX（每份 20 MB）。PDF
            使用文本层解析；扫描件请先通过桌面 Docling OCR 转为文本。
          </p>
          {project.permissions.includes("data_entry") && (
            <label className="button primary file-button">
              <Upload size={16} />
              {upload.busy ? "正在解析资料…" : "上传并解析"}
              <input
                disabled={upload.busy}
                type="file"
                accept=".txt,.md,.pdf,.docx,.xlsx"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  upload.run(async () => {
                    const form = new FormData();
                    form.append("file", file);
                    const response = await api(base + "/documents", {
                      method: "POST",
                      body: form,
                    });
                    await cache.invalidateQueries({
                      queryKey: ["documents", project.id],
                    });
                    if (response.status === "failed")
                      throw new Error(response.error || "资料解析失败");
                  }, "资料处理完成");
                  e.target.value = "";
                }}
              />
            </label>
          )}
          <Notice>{upload.error}</Notice>
          <Notice success>{upload.success}</Notice>
          <div className="documents">
            {docs.data?.documents.map((d) => (
              <div className="document" key={d.id}>
                <FileText />
                <section>
                  <strong>{d.name}</strong>
                  <small>
                    {d.chunk_count} 个片段 · {d.error || d.summary || d.status}
                  </small>
                </section>
                {project.permissions.includes("data_entry") && (
                  <button
                    aria-label={"删除资料 " + d.name}
                    className="icon-button"
                    onClick={() => {
                      if (confirm("删除该工程资料？"))
                        upload.run(async () => {
                          await api(base + "/documents/" + d.id, {
                            method: "DELETE",
                          });
                          await cache.invalidateQueries({
                            queryKey: ["documents", project.id],
                          });
                        });
                    }}
                  >
                    <Trash2 size={17} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </Modal>
      )}
      {modelOpen && (
        <Modal
          title="项目模型设置"
          onClose={() => !modelAction.busy && setModelOpen(false)}
        >
          <p className="muted model-settings-intro">
            当前设置只作用于本工程。API Key 只保存于服务器，读取时不会回显。
          </p>
          {!modelSettings.data?.editable && (
            <Notice>仅工程创建人或系统管理员可以修改模型设置。</Notice>
          )}
          <div className="model-settings-form">
            <label className="field">
              <span>模型接口地址</span>
              <input
                disabled={!modelSettings.data?.editable || modelAction.busy}
                value={modelDraft.base_url}
                onChange={(event) =>
                  setModelDraft({ ...modelDraft, base_url: event.target.value })
                }
                placeholder="例如：https://ark.cn-beijing.volces.com/api/v3"
              />
            </label>
            <label className="field">
              <span>模型或接入点</span>
              <input
                disabled={!modelSettings.data?.editable || modelAction.busy}
                value={modelDraft.model}
                onChange={(event) =>
                  setModelDraft({ ...modelDraft, model: event.target.value })
                }
                placeholder="填写模型 ID 或推理接入点 ID"
              />
            </label>
            <label className="field">
              <span>API Key</span>
              <input
                disabled={!modelSettings.data?.editable || modelAction.busy}
                type="password"
                value={modelDraft.api_key}
                onChange={(event) =>
                  setModelDraft({ ...modelDraft, api_key: event.target.value })
                }
                placeholder={
                  modelSettings.data?.api_key_configured
                    ? "留空保持现有 Key"
                    : "填写服务商 API Key"
                }
              />
            </label>
            {modelSettings.data?.api_key_configured && (
              <p className="muted model-settings-key-note">
                API Key 已配置，留空将保持不变
              </p>
            )}
            <label className="field">
              <span>请求超时（秒）</span>
              <input
                disabled={!modelSettings.data?.editable || modelAction.busy}
                type="number"
                min={1}
                max={300}
                value={modelDraft.timeout}
                onChange={(event) =>
                  setModelDraft({
                    ...modelDraft,
                    timeout: Number(event.target.value) || 90,
                  })
                }
              />
            </label>
            {modelSettings.data?.api_key_configured && (
              <label className="model-settings-clear-key">
                <input
                  disabled={!modelSettings.data?.editable || modelAction.busy}
                  type="checkbox"
                  checked={modelDraft.clear_api_key}
                  onChange={(event) =>
                    setModelDraft({
                      ...modelDraft,
                      clear_api_key: event.target.checked,
                    })
                  }
                />
                清除已保存的 API Key
              </label>
            )}
          </div>
          <Notice>{modelAction.error}</Notice>
          <Notice success>{modelAction.success}</Notice>
          <div className="modal-actions">
            <Button
              kind="primary"
              busy={modelAction.busy}
              disabled={!modelSettings.data?.editable}
              onClick={saveModelSettings}
            >
              保存模型设置
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
