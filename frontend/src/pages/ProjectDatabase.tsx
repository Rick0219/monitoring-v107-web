import { lazy, Suspense, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import { api, json, type DataSet, type Project, type Row } from "../api";
import { ChartQRCode } from "../components/ChartQRCode";
import { DatabaseEditor } from "../components/DatabaseEditor";
import { PageScrollTable } from "../components/PageScrollTable";
import {
  Button,
  Empty,
  Field,
  Modal,
  Notice,
  useAction,
} from "../components/Common";

const ReportChart = lazy(() => import("../components/ReportChart"));
export type ChartSettings = {
  measurement_key: string;
  mode: "all" | "top10" | "custom";
  points: string[];
  display: "daily" | "bar" | "history";
  end_date: string;
};
export type ChartData = {
  available_points: string[];
  control_bounds: [number | null, number | null];
  measurement_key: string;
  label: string;
  monitor: string;
  unit: string;
  dates: string[];
  history_dates: string[];
  effective_date: string;
  settings: ChartSettings;
  selected_points: string[];
  warnings: string[];
  points: {
    point: string;
    depth: number | null;
    current: number | null;
    values: { date: string; value: number | null }[];
  }[];
};
export type DatabaseData = Pick<
  ChartData,
  | "measurement_key"
  | "label"
  | "monitor"
  | "unit"
  | "dates"
  | "effective_date"
  | "warnings"
> & {
  end_date: string;
  columns: string[];
  rows: Row[];
  raw_rows: Row[];
  raw_columns: string[];
};
function useChart(project: Project, measurementKey: string) {
  return useQuery({
    queryKey: ["database-chart", project.id, measurementKey, project.revision],
    queryFn: () =>
      api<ChartData>(
        `/projects/${project.id}/charts?measurement_key=${encodeURIComponent(measurementKey)}`,
      ),
    enabled: !!measurementKey,
  });
}
export function ProjectDatabase({
  project,
  data,
  view,
  onDirty,
}: {
  project: Project;
  data: DataSet;
  view: "data" | "charts";
  onDirty: (dirty: boolean) => void;
}) {
  const [measurement, setMeasurement] = useState("");
  const [pageSize, setPageSize] = useState(30);
  const actual = data.catalog.some((item) => item.key === measurement)
    ? measurement
    : "";
  const measurementSelect = (
    <Field label="数据库测项">
      <select value={actual} onChange={(e) => setMeasurement(e.target.value)}>
        <option value="">
          {view === "charts" ? "全部测项" : "选择测项（默认第一项）"}
        </option>
        {data.catalog.map((item) => (
          <option key={item.key} value={item.key}>
            {item.label}
          </option>
        ))}
      </select>
    </Field>
  );
  return (
    <section
      className={`database-page ${view === "data" ? "database-page--data" : ""}`}
    >
      <div className="panel database-header">
        <div>
          <h2>{view === "data" ? "数据库数据" : "数据库图表"}</h2>
          <p>
            {view === "data"
              ? "选择日期，查看原始监测数据及日报计算数据。"
              : "按日报口径查看各测项图表，显示设置自动保存。"}
          </p>
        </div>
        {(view === "charts" || !data.catalog.length) && measurementSelect}
      </div>
      {!data.catalog.length ? (
        <div className="panel">
          <Empty title="暂无监测数据">
            {project.permissions.includes("data_entry")
              ? "先在“数据录入”保存数据，或导入桌面工程。"
              : "请联系有数据录入权限的工程成员添加监测数据。"}
          </Empty>
        </div>
      ) : view === "data" ? (
        <DatabaseTable
          key={actual || data.catalog[0].key}
          project={project}
          measurementKey={actual || data.catalog[0].key}
          onDirty={onDirty}
          measurementSelect={measurementSelect}
          pageSize={pageSize}
          onPageSize={setPageSize}
        />
      ) : (
        <div className="database-chart-list">
          {data.catalog
            .filter((item) => !actual || actual === item.key)
            .map((item) => (
              <ChartCard
                key={item.key}
                project={project}
                measurementKey={item.key}
                availablePoints={item.points}
              />
            ))}
        </div>
      )}
    </section>
  );
}
function DatabaseTable({
  project,
  measurementKey,
  onDirty,
  measurementSelect,
  pageSize,
  onPageSize,
}: {
  project: Project;
  measurementKey: string;
  onDirty: (dirty: boolean) => void;
  measurementSelect: ReactNode;
  pageSize: number;
  onPageSize: (size: number) => void;
}) {
  const query = useQuery({
    queryKey: ["database-table", project.id, measurementKey, project.revision],
    queryFn: () =>
      api<DatabaseData>(
        `/projects/${project.id}/database?measurement_key=${encodeURIComponent(measurementKey)}`,
      ),
    enabled: !!measurementKey,
  });
  const cache = useQueryClient(),
    action = useAction();
  const [editing, setEditing] = useState(false);
  const [source, setSource] = useState("report"),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(0);
  const [sort, setSort] = useState({ column: "", descending: false });
  const tableStart = useRef<HTMLDivElement>(null);
  const raw = query.data?.raw_rows || [];
  const rows = source === "raw" ? raw : query.data?.rows || [];
  const columns =
    source === "raw"
      ? query.data?.raw_columns || []
      : query.data?.columns || [];
  const filtered = rows.filter((row) =>
    Object.values(row).some((value) =>
      String(value ?? "")
        .toLowerCase()
        .includes(search.toLowerCase()),
    ),
  );
  if (sort.column)
    filtered.sort(
      (a, b) =>
        String(a[sort.column] ?? "").localeCompare(
          String(b[sort.column] ?? ""),
          "zh-CN",
          { numeric: true },
        ) * (sort.descending ? -1 : 1),
    );
  const maxPage = pageSize
      ? Math.max(0, Math.ceil(filtered.length / pageSize) - 1)
      : 0,
    currentPage = Math.min(page, maxPage);
  const shown = pageSize
    ? filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize)
    : filtered;
  function changePage(next: number) {
    setPage(next);
    requestAnimationFrame(() =>
      tableStart.current?.scrollIntoView({ block: "start" }),
    );
  }
  return (
    <section className="panel database-table">
      <div className="database-table-tools">
        {measurementSelect}
        <Field label="数据库日期">
          <select
            disabled={!query.data || action.busy}
            value={query.data?.end_date || ""}
            onChange={(e) => {
              const chart = query.data;
              if (!chart) return;
              const end_date = e.target.value;
              action.run(async () => {
                await api(
                  `/projects/${project.id}/database-date`,
                  json(
                    {
                      measurement_key: measurementKey,
                      end_date,
                    },
                    "PUT",
                  ),
                );
                await cache.invalidateQueries({
                  queryKey: ["database-table", project.id, measurementKey],
                });
                await cache.invalidateQueries({
                  queryKey: ["database-chart", project.id, measurementKey],
                });
                setPage(0);
              });
            }}
          >
            <option value="">最新日期（自动更新）</option>
            {query.data?.dates.map((date) => (
              <option key={date}>{date}</option>
            ))}
          </select>
        </Field>
        <Field label="数据内容">
          <select
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setPage(0);
              setSort({ column: "", descending: false });
            }}
          >
            <option value="report">日报计算数据</option>
            <option value="raw">原始监测数据</option>
          </select>
        </Field>
        <Field label="筛选数据">
          <input
            placeholder="搜索点号或表格内容"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
          />
        </Field>
        {project.permissions.includes("data_entry") &&
          query.data?.monitor !== "tilt" && (
            <Button
              disabled={!raw.length || action.busy}
              onClick={() => setEditing(true)}
            >
              编辑当日数据
            </Button>
          )}
        <span className="muted database-result-count">
          共 {filtered.length} 行
          {query.data?.effective_date
            ? ` · 日期 ${query.data.effective_date}`
            : ""}
        </span>
      </div>
      <Notice>{query.error?.message || action.error}</Notice>
      {query.data?.warnings.map((w) => (
        <Notice key={w}>{w}</Notice>
      ))}
      {query.isPending ? (
        <p>正在计算日报数据…</p>
      ) : (
        <>
          <div className="database-table-start" ref={tableStart}>
            <PageScrollTable>
              <table
                className="database-read-table"
                aria-label={query.data?.label || "监测数据"}
              >
                <thead>
                  <tr>
                    {columns.map((column) => (
                      <th
                        key={column}
                        aria-sort={
                          sort.column === column
                            ? sort.descending
                              ? "descending"
                              : "ascending"
                            : "none"
                        }
                      >
                        <button
                          className="column-sort"
                          onClick={() => {
                            setPage(0);
                            setSort({
                              column,
                              descending:
                                sort.column === column && !sort.descending,
                            });
                          }}
                        >
                          {column}
                          {sort.column === column
                            ? sort.descending
                              ? " ↓"
                              : " ↑"
                            : ""}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((row, index) => (
                    <tr key={index}>
                      {columns.map((column) => (
                        <td key={column}>{String(row[column] ?? "—")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </PageScrollTable>
          </div>
          {!filtered.length && <Empty title="没有符合条件的数据" />}
          <nav
            className="database-pagination database-data-pagination"
            aria-label="数据库分页"
          >
            <span className="database-page-total">
              共 {filtered.length} 条数据
            </span>
            <Field label="每页条数">
              <select
                value={pageSize || "all"}
                onChange={(event) => {
                  onPageSize(
                    event.target.value === "all"
                      ? 0
                      : Number(event.target.value),
                  );
                  changePage(0);
                }}
              >
                {[10, 20, 30, 40, 50].map((size) => (
                  <option key={size} value={size}>
                    {size} 条 / 页
                  </option>
                ))}
                <option value="all">全部数据</option>
              </select>
            </Field>
            <span aria-live="polite">
              第 {currentPage + 1} / {maxPage + 1} 页
            </span>
            <Button
              disabled={!currentPage}
              onClick={() => changePage(currentPage - 1)}
            >
              上一页
            </Button>
            <Button
              disabled={currentPage === maxPage}
              onClick={() => changePage(currentPage + 1)}
            >
              下一页
            </Button>
          </nav>
          <p className="database-note">
            原始数据和日报计算数据均对应所选日期，累计值保留历史初始基准。此日期与当前账号的该测项图表同步。
          </p>
        </>
      )}
      {editing && query.data && project.permissions.includes("data_entry") && (
        <DatabaseEditor
          project={project}
          chart={query.data}
          onDirty={onDirty}
          onClose={() => setEditing(false)}
        />
      )}
    </section>
  );
}
export function ChartCard({
  project,
  measurementKey,
  availablePoints: suppliedPoints,
}: {
  project: Project;
  measurementKey: string;
  availablePoints?: string[];
}) {
  const query = useChart(project, measurementKey),
    cache = useQueryClient(),
    action = useAction();
  const [choose, setChoose] = useState(false),
    [draft, setDraft] = useState<string[]>([]),
    [search, setSearch] = useState("");
  const chart = query.data;
  const availablePoints = suppliedPoints || chart?.available_points || [];
  async function save(settings: ChartSettings) {
    await action.run(async () => {
      await api(
        `/projects/${project.id}/chart-settings`,
        json(settings, "PUT"),
      );
      await cache.invalidateQueries({
        queryKey: ["database-chart", project.id, measurementKey],
      });
      await cache.invalidateQueries({
        queryKey: ["database-table", project.id, measurementKey],
      });
      setChoose(false);
    }, "已保存，下次进入自动恢复");
  }
  function openPoints() {
    if (!chart) return;
    setDraft(
      (chart.settings.mode === "custom"
        ? chart.settings.points
        : chart.selected_points
      ).filter((point) => availablePoints.includes(point)),
    );
    setSearch("");
    setChoose(true);
  }
  if (!chart)
    return (
      <section className="panel">
        <h3>{measurementKey}</h3>
        <Notice>{query.error?.message}</Notice>
        {query.isPending && <p>正在生成测项图表…</p>}
      </section>
    );
  const pointValues = new Map(
    chart.points.map((point) => [point.point, point.current]),
  );
  const selected = new Set(chart.selected_points),
    depth = chart.monitor === "inclinometer";
  return (
    <section
      className="panel database-chart-card"
      aria-label={chart.label + "图表"}
    >
      <header className="chart-card-heading">
        <div className="chart-title-and-code">
          <div>
            <span className="eyebrow">监测日报 · {chart.unit}</span>
            <h3>{chart.label}</h3>
          </div>
          <ChartQRCode
            projectId={project.id}
            measurementKey={measurementKey}
            label={chart.label}
          />
        </div>
        <span className="chart-count">
          已显示 {selected.size} / {chart.points.length} 个
          {depth ? "深度" : "点位"}
        </span>
      </header>
      <div className="chart-controls">
        <Field label="图表形式">
          <select
            disabled={action.busy}
            value={chart.settings.display}
            onChange={(e) =>
              save({
                ...chart.settings,
                display: e.target.value as ChartSettings["display"],
              })
            }
          >
            <option value="daily">
              {depth ? "日报深度剖面" : "日报点位对比"}
            </option>
            {!depth && <option value="bar">累计值柱状对比</option>}
            <option value="history">累计值历史曲线</option>
          </select>
        </Field>
        <Field label="点位显示">
          <select
            disabled={action.busy}
            value={chart.settings.mode}
            onChange={(e) =>
              e.target.value === "custom"
                ? openPoints()
                : save({
                    ...chart.settings,
                    mode: e.target.value as ChartSettings["mode"],
                    points: chart.settings.points.filter((p) =>
                      availablePoints.includes(p),
                    ),
                  })
            }
          >
            <option value="top10">累计值最大前 10 个点</option>
            <option value="all">所有点</option>
            <option value="custom">用户自选点</option>
          </select>
        </Field>
        <Field label="监测日期">
          <select
            disabled={action.busy}
            value={chart.settings.end_date}
            onChange={(e) =>
              save({
                ...chart.settings,
                end_date: e.target.value,
                points: chart.settings.points.filter((p) =>
                  availablePoints.includes(p),
                ),
              })
            }
          >
            <option value="">最新日期（自动更新）</option>
            {chart.dates.map((date) => (
              <option key={date}>{date}</option>
            ))}
          </select>
        </Field>
        <Button busy={action.busy} onClick={openPoints}>
          <SlidersHorizontal size={16} />
          勾选点位
        </Button>
      </div>
      <p className="database-note">
        {chart.effective_date || "暂无日期"} ·{" "}
        {chart.settings.display === "history"
          ? "前 10 点按截至所选日期的历史累计绝对峰值排序"
          : "前 10 点按本次累计值绝对值降序排列"}
        ，保留正负号。
        {depth &&
          (chart.settings.display === "history"
            ? "各期累计位移按日期叠加在同一深度剖面；缺测处断开。"
            : "剖面按深度排列；点位选择对应监测深度。")}
      </p>
      <Notice>{action.error}</Notice>
      <Notice success>{action.success}</Notice>
      {chart.warnings.map((w) => (
        <Notice key={w}>{w}</Notice>
      ))}
      {selected.size ? (
        <Suspense
          fallback={<div className="report-chart-loading">正在绘制图表…</div>}
        >
          <ReportChart data={chart} />
        </Suspense>
      ) : (
        <Empty title="暂无可绘制点位">
          请勾选点位，或选择有有效读数的日期。
        </Empty>
      )}
      <details className="chart-value-list">
        <summary>查看所选点位数值（{selected.size}）</summary>
        <div>
          {chart.selected_points.map((point) => (
            <span key={point}>
              <b>{depth ? `深度 ${point} m` : point}</b>
              <span>
                {pointValues.get(point) ?? "缺测"} {chart.unit}
              </span>
            </span>
          ))}
        </div>
      </details>
      {choose && (
        <Modal
          title={`勾选点位 · ${chart.label}`}
          onClose={() => !action.busy && setChoose(false)}
        >
          <Field label="搜索点位">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="输入点号或深度"
            />
          </Field>
          <div className="database-pagination">
            <span>已选 {draft.length} 个</span>
            <Button onClick={() => setDraft(availablePoints)}>全选</Button>
            <Button onClick={() => setDraft([])}>清空</Button>
          </div>
          <div className="point-picker">
            {availablePoints
              .filter((p) => p.toLowerCase().includes(search.toLowerCase()))
              .map((point) => (
                <label key={point}>
                  <input
                    type="checkbox"
                    checked={draft.includes(point)}
                    onChange={(e) =>
                      setDraft(
                        e.target.checked
                          ? [...draft, point]
                          : draft.filter((p) => p !== point),
                      )
                    }
                  />
                  {point}
                </label>
              ))}
          </div>
          <Notice>{action.error}</Notice>
          <div className="modal-actions">
            <Button disabled={action.busy} onClick={() => setChoose(false)}>
              取消
            </Button>
            <Button
              kind="primary"
              busy={action.busy}
              onClick={() =>
                save({
                  ...chart.settings,
                  mode: "custom",
                  points: draft,
                  end_date: chart.dates.includes(chart.settings.end_date)
                    ? chart.settings.end_date
                    : "",
                })
              }
            >
              应用并记住
            </Button>
          </div>
        </Modal>
      )}
    </section>
  );
}
