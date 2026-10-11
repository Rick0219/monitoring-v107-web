import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, json, type Project, type Row } from "../api";
import type { DatabaseData } from "../pages/ProjectDatabase";
import { Button, Modal, Notice, useAction } from "./Common";
import { PageScrollTable } from "./PageScrollTable";

export function DatabaseEditor({
  project,
  chart,
  onDirty,
  onClose,
}: {
  project: Project;
  chart: DatabaseData;
  onDirty: (dirty: boolean) => void;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    structuredClone(chart.raw_rows),
  );
  const [revision] = useState(project.revision);
  const [dirty, setDirty] = useState(false),
    [page, setPage] = useState(0);
  const action = useAction(),
    cache = useQueryClient();
  function close() {
    if (action.busy || (dirty && !confirm("当日数据尚未保存，放弃修改？")))
      return;
    onDirty(false);
    onClose();
  }
  return (
    <Modal title={`编辑当日数据 · ${chart.effective_date}`} onClose={close}>
      <p className="muted">
        修改原始读数后，累计值、图表和报告会重新计算。日期及测点身份保持不变。
      </p>
      <div className="database-editor-table">
        <PageScrollTable label="当日编辑表格">
          <table>
            <thead>
              <tr>
                {chart.raw_columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(page * 50, (page + 1) * 50).map((row, i) => (
                <tr key={i}>
                  {chart.raw_columns.map((c) => (
                    <td key={c}>
                      {[
                        "时间",
                        "深度",
                        "点号",
                        "点位",
                        "点号1",
                        "点号2",
                        "编号",
                        "序号",
                        "轴力（kN）",
                        "传感器类型",
                        "管口高程（m）",
                      ].includes(c) ? (
                        String(row[c] ?? "")
                      ) : (
                        <input
                          aria-label={`第${page * 50 + i + 1}行 ${c}`}
                          value={String(row[c] ?? "")}
                          onChange={(e) => {
                            const next = [...rows];
                            next[page * 50 + i] = {
                              ...row,
                              [c]: e.target.value,
                            };
                            setRows(next);
                            setDirty(true);
                            onDirty(true);
                          }}
                        />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </PageScrollTable>
      </div>
      <div className="database-pagination">
        <span>
          共 {rows.length} 行 · 第 {page + 1} 页
        </span>
        <Button disabled={!page} onClick={() => setPage(page - 1)}>
          上一页
        </Button>
        <Button
          disabled={(page + 1) * 50 >= rows.length}
          onClick={() => setPage(page + 1)}
        >
          下一页
        </Button>
      </div>
      <Notice>{action.error}</Notice>
      <div className="modal-actions">
        <Button disabled={action.busy} onClick={close}>
          取消
        </Button>
        <Button
          kind="primary"
          busy={action.busy}
          disabled={!dirty}
          onClick={() =>
            action.run(async () => {
              await api(
                `/projects/${project.id}/database`,
                json(
                  {
                    revision,
                    measurement_key: chart.measurement_key,
                    date: chart.effective_date,
                    rows,
                  },
                  "PUT",
                ),
              );
              await cache.invalidateQueries({
                queryKey: ["project", project.id],
              });
              await cache.invalidateQueries({
                queryKey: ["project-data", project.id],
              });
              await cache.invalidateQueries({
                queryKey: ["database-chart", project.id],
              });
              await cache.invalidateQueries({
                queryKey: ["database-table", project.id],
              });
              await cache.invalidateQueries({ queryKey: ["projects"] });
              onDirty(false);
              onClose();
            })
          }
        >
          保存当日数据
        </Button>
      </div>
    </Modal>
  );
}
