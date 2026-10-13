import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Save,
  Upload,
  Download,
  ArrowLeft,
  Settings2,
} from "lucide-react";
import {
  api,
  json,
  saveText,
  download,
  type DataSet,
  type Project,
  type Row,
} from "../api";
import {
  Button,
  Empty,
  Field,
  Form,
  Modal,
  Notice,
  useAction,
} from "../components/Common";
import { EntryGrid } from "../components/EntryGrid";
import { LevelAdjustmentImport } from "../components/LevelAdjustmentImport";
import {
  EntryTypePicker,
  entryTypes,
  entryLabel,
} from "../components/EntryTypePicker";
import {
  EntryParameters,
  parameterTitles,
  type EntryData,
} from "../components/EntryParameters";
import { parseCSV, toCSV } from "../csv";

const localDate = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
};
const hints: Record<string, string> = {
  level:
    "按监测日期录入点号、高程测量值（m）及备注。可复制已有点号，粘贴 Excel 单元格。",
  horizontal:
    "按监测日期录入点号、X 坐标、Y 坐标（m）及备注。累计位移由数据库和报告自动计算。",
  water: "先设置水位参数，点位与管口高程自动带入；填写水位读数（m）及备注。",
  axial:
    "先设置轴力参数，再新增点位加载全部编号；输入频率（Hz），轴力（kN）自动计算。",
  tilt: "选择关联的水准测项，在测点参数中选择两点和距离；倾斜度由累计沉降差自动计算，不能手填。",
  inclinometer:
    "先设置孔号、步长和深度；按期录入深度与测值（mm），保存后自动合并为数据库日期列。",
};

export function DataEntry({
  project,
  data,
  onDirty,
}: {
  project: Project;
  data: DataSet;
  onDirty: (dirty: boolean) => void;
}) {
  const [key, setKey] = useState(""),
    [type, setType] = useState(""),
    [name, setName] = useState("建筑物位移");
  const [createOpen, setCreateOpen] = useState(false),
    [createError, setCreateError] = useState("");
  const [date, setDate] = useState(localDate),
    [batch, setBatch] = useState(""),
    [rows, setRows] = useState<Row[]>([]),
    [dirty, setDirty] = useState(false);
  const [filter, setFilter] = useState(""),
    [parameterOpen, setParameterOpen] = useState(false),
    [addPoint, setAddPoint] = useState(false),
    [point, setPoint] = useState("");
  const [addCount, setAddCount] = useState(1),
    [imported, setImported] = useState<Row[] | null>(null),
    [calcError, setCalcError] = useState("");
  const cache = useQueryClient(),
    action = useAction(),
    state = useRef({
      dirty: false,
      identity: "",
      baseline: "",
      revision: project.revision,
    });
  const monitor = key.split(":")[0],
    observed = date + batch,
    identity = key + "|" + observed,
    base = `/projects/${project.id}/entry`;
  const query = useQuery({
    queryKey: ["entry-period", project.id, key, observed, project.revision],
    queryFn: () =>
      api<EntryData>(
        `${base}?measurement_key=${encodeURIComponent(key)}&date=${encodeURIComponent(observed)}`,
      ),
    enabled: !!key && !!date,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[2] === key &&
      previousQuery?.queryKey[3] === observed
        ? previous
        : undefined,
  });
  const current = query.data;
  useEffect(() => {
    if (!current) return;
    const baseline = JSON.stringify(current.rows);
    if (state.current.dirty && state.current.identity === identity) {
      if (state.current.baseline === baseline)
        state.current.revision = current.revision;
      return;
    }
    state.current = {
      dirty: false,
      identity,
      baseline,
      revision: current.revision,
    };
    setRows(structuredClone(current.rows));
    setDirty(false);
    onDirty(false);
    setCalcError("");
  }, [current, identity]);
  useEffect(() => {
    if (!dirty || monitor !== "axial") return;
    let stale = false;
    const timer = setTimeout(() => {
      api<{ rows: Row[] }>(
        base + "/preview",
        json({ measurement_key: key, date: observed, rows }),
      )
        .then((result) => {
          if (stale) return;
          setCalcError("");
          if (JSON.stringify(result.rows) !== JSON.stringify(rows))
            setRows(result.rows);
        })
        .catch((error) => {
          if (!stale) setCalcError(error.message);
        });
    }, 350);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [rows, dirty, key, observed]);
  function touch(next: Row[]) {
    setRows(
      next.map((row, index) => ({
        ...row,
        ...(current?.columns.includes("序号") ? { 序号: index + 1 } : {}),
        ...(current?.columns.includes("时间") ? { 时间: observed } : {}),
      })),
    );
    state.current.dirty = true;
    setDirty(true);
    onDirty(true);
  }
  function discard() {
    if (dirty && !confirm("有未保存的数据，切换将放弃修改。继续？"))
      return false;
    state.current.dirty = false;
    if (current) setRows(structuredClone(current.rows));
    setDirty(false);
    onDirty(false);
    setFilter("");
    setCalcError("");
    action.clearStatus();
    return true;
  }
  async function refresh() {
    await cache.invalidateQueries({ queryKey: ["project", project.id] });
    await cache.invalidateQueries({ queryKey: ["project-data", project.id] });
    await cache.invalidateQueries({ queryKey: ["entry-period", project.id] });
    await cache.invalidateQueries({ queryKey: ["database-table", project.id] });
    await cache.invalidateQueries({ queryKey: ["database-chart", project.id] });
    await cache.invalidateQueries({ queryKey: ["projects"] });
  }
  const levelNames = data.catalog
    .filter((item) => item.key.startsWith("level:"))
    .map((item) => item.key.slice(6));
  const names = Array.from(
    new Set([
      "建筑物位移",
      "地表位移",
      "管线位移",
      "桩顶竖向位移",
      ...levelNames,
    ]),
  );
  const available =
    current?.parameters
      .filter((p) => !rows.some((r) => r["编号"] === p["编号"]))
      .map((p) => String(p["点号"])) || [];
  const measurementKeys = Array.from(
    new Set([
      ...(data.entry_sets || []),
      ...data.catalog.map((item) => item.key),
      ...(key ? [key] : []),
    ]),
  );
  const selectedType = entryTypes.find((item) => item.key === type);
  function selectType(next: string) {
    if (!discard()) return;
    const defaultName =
      next === "axial"
        ? "第一道支撑"
        : next === "inclinometer"
          ? "CX01"
          : next === "tilt"
            ? levelNames[0] || ""
            : "建筑物位移";
    const existing = measurementKeys.find(
      (value) => value.split(":")[0] === next,
    );
    const defaultKey = ["water", "horizontal"].includes(next)
      ? next
      : defaultName
        ? `${next}:${defaultName}`
        : "";
    setType(next);
    setName(defaultName);
    setKey(existing || defaultKey);
    setRows([]);
  }
  if (!type) return <EntryTypePicker onSelect={selectType} />;
  return (
    <section className="panel entry-page">
      <fieldset disabled={action.busy}>
        <div className="panel-heading">
          <div>
            <div className="entry-heading-import">
              <LevelAdjustmentImport project={project} data={data} onApplied={refresh} />
            </div>
            <h2 className="entry-type-title">
              <img src={selectedType?.icon} alt="" />
              {selectedType?.name}数据录入{" "}
              {dirty && <span className="pill warn">未保存</span>}
            </h2>
            <p>选择测项和监测期次，完成参数设置后录入，核对后保存。</p>
          </div>
          <div className="entry-heading-actions">
            <Button
              onClick={() => {
                if (discard()) {
                  setType("");
                  setKey("");
                  setRows([]);
                }
              }}
            >
              <ArrowLeft size={16} />
              更换监测类型
            </Button>
          </div>
        </div>
        {!["water", "horizontal"].includes(type) && (
          <div className="data-setup">
            <Field label="当前测项">
              <select
                value={key}
                onChange={(event) => {
                  if (discard()) setKey(event.target.value);
                }}
              >
                {!key && <option value="">选择或新建测项</option>}
                {measurementKeys
                  .filter((value) => value.split(":")[0] === type)
                  .map((value) => (
                    <option key={value} value={value}>
                      {entryLabel(value)}
                    </option>
                  ))}
              </select>
            </Field>
            <Button
              disabled={type === "tilt" && !levelNames.length}
              onClick={() => {
                setName(type === "tilt" ? levelNames[0] || "" : "");
                setCreateError("");
                setCreateOpen(true);
              }}
            >
              <Plus size={16} />
              新建测项
            </Button>
          </div>
        )}
        {createOpen && (
          <Modal title="新建测项" onClose={() => setCreateOpen(false)}>
            <Form
              onSubmit={() => {
                const value = name.trim();
                if (!value) {
                  setCreateError(
                    type === "tilt"
                      ? "请选择关联水准测项"
                      : type === "inclinometer"
                        ? "请填写孔号"
                        : "请填写测项名称",
                  );
                  return;
                }
                const nextKey = `${type}:${value}`;
                if (nextKey !== key && !discard()) return;
                setKey(nextKey);
                setCreateOpen(false);
              }}
            >
              <p className="muted">
                监测类型：{selectedType?.name}。确认后进入对应录入表。
              </p>
              <Field
                label={
                  type === "tilt"
                    ? "关联水准测项"
                    : type === "inclinometer"
                      ? "孔号"
                      : "测项名称"
                }
              >
                {type === "tilt" ? (
                  <select
                    autoFocus
                    value={name}
                    onChange={(event) => {
                      setName(event.target.value);
                      setCreateError("");
                    }}
                  >
                    <option value="">选择水准测项</option>
                    {levelNames.map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    autoFocus
                    maxLength={100}
                    value={name}
                    placeholder={
                      type === "inclinometer"
                        ? "例如：CX01"
                        : type === "axial"
                          ? "例如：第一道支撑"
                          : "例如：地表位移"
                    }
                    list={type === "level" ? "level-names" : undefined}
                    onChange={(event) => {
                      setName(event.target.value);
                      setCreateError("");
                    }}
                  />
                )}
              </Field>
              {type === "level" && (
                <datalist id="level-names">
                  {names.map((value) => (
                    <option key={value} value={value} />
                  ))}
                </datalist>
              )}
              <Notice>{createError}</Notice>
              <div className="modal-actions">
                <Button type="button" onClick={() => setCreateOpen(false)}>
                  取消
                </Button>
                <Button type="submit" kind="primary">
                  确认新建
                </Button>
              </div>
            </Form>
          </Modal>
        )}
        <Notice>{action.error || query.error?.message}</Notice>
        <Notice success>{action.success}</Notice>
        {type === "tilt" && !levelNames.length ? (
          <div className="entry-prerequisite">
            <Empty title="倾斜数据需要关联水准测项">
              请先录入水准数据，再配置倾斜测点参数。
            </Empty>
            <Button kind="primary" onClick={() => selectType("level")}>
              去录入水准数据
            </Button>
          </div>
        ) : !key ? (
          <Empty title="先选择一个监测测项">
            选择已有测项，或点击“新建测项”填写名称。
          </Empty>
        ) : !current ? (
          <p>正在读取当前期次…</p>
        ) : (
          <>
            <div className="entry-period-controls">
              <Field label="监测日期">
                <input
                  type="date"
                  value={date}
                  onChange={(event) => {
                    if (event.target.value && discard())
                      setDate(event.target.value);
                  }}
                />
              </Field>
              <Field label="观测批次">
                <select
                  value={batch}
                  onChange={(event) => {
                    if (discard()) setBatch(event.target.value);
                  }}
                >
                  <option value="">常规观测</option>
                  <option value="（加密）">加密观测</option>
                </select>
              </Field>
              <Field label="载入已存期次">
                <select
                  value={current.dates.includes(observed) ? observed : ""}
                  onChange={(event) => {
                    if (event.target.value && discard()) {
                      setDate(event.target.value.slice(0, 10));
                      setBatch(
                        event.target.value.includes("加密") ? "（加密）" : "",
                      );
                    }
                  }}
                >
                  <option value="">选择已保存日期</option>
                  {current.dates.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </Field>
            </div>
            <div
              className={`entry-guidance ${current.parameter_columns.length ? "has-parameters" : ""}`}
            >
              <div>
                <strong>
                  {current.parameter_columns.length ? "参数设置" : "录入说明"}
                </strong>
                <p>{hints[monitor]}</p>
              </div>
              {current.parameter_columns.length > 0 && (
                <Button
                  className="entry-parameter-button"
                  onClick={() => {
                    if (discard()) {
                      setRows(structuredClone(current.rows));
                      setParameterOpen(true);
                    }
                  }}
                >
                  <Settings2 size={17} />
                  {parameterTitles[monitor]}
                </Button>
              )}
            </div>
            <div className="entry-table-heading">
              <h3>单期录入表</h3>
              <span>
                {observed} · {rows.length} 行
              </span>
            </div>
            <div className="toolbar entry-toolbar">
              <div className="toolbar-group">
                {monitor === "axial" ? (
                  <Button
                    onClick={() => {
                      if (!available.length)
                        return action.setError(
                          "请先设置轴力参数，或当前参数点位已全部加载",
                        );
                      setPoint(available[0]);
                      setAddPoint(true);
                    }}
                  >
                    新增点位
                  </Button>
                ) : (
                  !["water", "tilt"].includes(monitor) && (
                    <>
                      <input
                        className="entry-row-count"
                        type="number"
                        aria-label="新增行数"
                        min={1}
                        max={10000}
                        value={addCount}
                        onChange={(event) =>
                          setAddCount(Number(event.target.value))
                        }
                      />
                      <Button
                        onClick={() => {
                          if (
                            !Number.isInteger(addCount) ||
                            addCount < 1 ||
                            addCount + rows.length > 20000
                          )
                            return action.setError(
                              "请填写有效行数，最多 20000 行",
                            );
                          touch([
                            ...rows,
                            ...Array.from({ length: addCount }, (_, i) =>
                              Object.fromEntries(
                                current.columns.map((c) => [
                                  c,
                                  c === "时间"
                                    ? observed
                                    : c === "序号"
                                      ? rows.length + i + 1
                                      : "",
                                ]),
                              ),
                            ),
                          ]);
                        }}
                      >
                        <Plus size={16} />
                        {addCount === 1 ? "新增一行" : "添加数据"}
                      </Button>
                      {!!current.copy_rows.length && !rows.length && (
                        <Button
                          onClick={() =>
                            touch(structuredClone(current.copy_rows))
                          }
                        >
                          复制已有点号
                        </Button>
                      )}
                    </>
                  )
                )}
                {monitor !== "tilt" && (
                  <>
                    <label className="button file-button">
                      <Upload size={16} />
                      Excel / CSV 导入
                      <input
                        type="file"
                        disabled={action.busy}
                        accept=".xlsx,.xlsm,.csv"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (!file) return;
                          void action.run(async () => {
                            if (file.size > 20 * 1024 * 1024)
                              throw new Error("文件不能超过 20 MB");
                            let result: { rows: Row[] };
                            if (file.name.toLowerCase().endsWith(".csv"))
                              result = await api(
                                base + "/preview",
                                json({
                                  measurement_key: key,
                                  date: observed,
                                  rows: parseCSV(await file.text()),
                                }),
                              );
                            else {
                              const form = new FormData();
                              form.append("file", file);
                              result = await api(
                                `${base}/import?measurement_key=${encodeURIComponent(key)}&date=${encodeURIComponent(observed)}`,
                                { method: "POST", body: form },
                              );
                            }
                            setImported(result.rows);
                          });
                          event.target.value = "";
                        }}
                      />
                    </label>
                    <Button
                      onClick={() =>
                        action.run(async () =>
                          download(
                            `${base}/template?measurement_key=${encodeURIComponent(key)}`,
                            `${key.replace(":", "-")}-录入模板.xlsx`,
                          ),
                        )
                      }
                    >
                      下载 Excel 模板
                    </Button>
                  </>
                )}
                <Button
                  onClick={() =>
                    saveText(
                      toCSV(rows, current.columns),
                      key.replace(":", "-") + ".csv",
                      "text/csv;charset=utf-8",
                    )
                  }
                >
                  <Download size={16} />
                  导出 CSV
                </Button>
              </div>
              <Button
                kind="primary"
                busy={action.busy}
                disabled={!dirty && monitor !== "tilt"}
                onClick={() =>
                  action.run(async () => {
                    await api(
                      base,
                      json(
                        {
                          revision: state.current.revision,
                          measurement_key: key,
                          date: observed,
                          rows,
                        },
                        "PUT",
                      ),
                    );
                    state.current.dirty = false;
                    setDirty(false);
                    onDirty(false);
                    await refresh();
                  }, "数据已保存到当前工程")
                }
              >
                <Save size={16} />
                保存数据
              </Button>
            </div>
            <Notice>{calcError}</Notice>
            <div className="table-tools">
              <input
                aria-label="筛选数据"
                placeholder="筛选点位或备注…"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
              />
              <small>
                点击起始单元格按 Ctrl+V
                可粘贴多行多列；空表可用“批量粘贴”，核对后保存。
              </small>
            </div>
            <EntryGrid
              key={identity}
              rows={rows}
              columns={current.columns}
              readonly={(c) => current.readonly.includes(c)}
              onChange={touch}
              filter={filter}
              allowAdd={["level", "horizontal", "inclinometer"].includes(
                monitor,
              )}
              allowDelete={!["water", "tilt"].includes(monitor)}
              groupAxial={monitor === "axial"}
            />
            {!rows.length && (
              <Empty title="当前期次暂无数据">
                {["water", "tilt"].includes(monitor)
                  ? "先配置参数，再填写或查看当前期数据。"
                  : "添加数据、复制点位或导入 Excel。"}
              </Empty>
            )}
            {parameterOpen && (
              <EntryParameters
                projectId={project.id}
                data={current}
                onClose={() => setParameterOpen(false)}
                onSaved={refresh}
              />
            )}
            {addPoint && (
              <Modal title="新增轴力点位" onClose={() => setAddPoint(false)}>
                <Field label="选择点号">
                  <select
                    value={point}
                    onChange={(event) => setPoint(event.target.value)}
                  >
                    {Array.from(new Set(available)).map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </Field>
                <div className="modal-actions">
                  <Button onClick={() => setAddPoint(false)}>取消</Button>
                  <Button
                    kind="primary"
                    onClick={() => {
                      const added = current.parameters
                        .filter(
                          (p) =>
                            p["点号"] === point &&
                            !rows.some((r) => r["编号"] === p["编号"]),
                        )
                        .map((p) => ({
                          时间: observed,
                          点号: point,
                          编号: p["编号"],
                          频率: "",
                          "轴力（kN）": "/",
                          备注: "",
                        }));
                      touch(
                        [...rows, ...added].sort((a, b) =>
                          String(a["点号"]).localeCompare(
                            String(b["点号"]),
                            "zh-CN",
                            { numeric: true },
                          ),
                        ),
                      );
                      setAddPoint(false);
                    }}
                  >
                    加载全部编号
                  </Button>
                </div>
              </Modal>
            )}
            {imported && (
              <Modal title="导入预览" onClose={() => setImported(null)}>
                <p>
                  共 {imported.length} 行，确认后替换当前录入表；监测日期统一为{" "}
                  {observed}。点击“保存数据”后才写入数据库。
                </p>
                <EntryGrid
                  rows={imported}
                  columns={current.columns}
                  readonly={() => true}
                  onChange={() => {}}
                  labelPrefix="预览"
                />
                <div className="modal-actions">
                  <Button onClick={() => setImported(null)}>取消</Button>
                  <Button
                    kind="primary"
                    onClick={() => {
                      touch(imported);
                      setImported(null);
                    }}
                  >
                    应用到录入表
                  </Button>
                </div>
              </Modal>
            )}
          </>
        )}
      </fieldset>
    </section>
  );
}
