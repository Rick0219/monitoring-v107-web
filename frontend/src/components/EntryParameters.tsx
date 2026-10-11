import { useState } from "react";
import { api, json, type Row } from "../api";
import { Button, Modal, Notice, useAction } from "./Common";
import { EntryGrid } from "./EntryGrid";

export type EntryData = {
  revision: number;
  measurement_key: string;
  date: string;
  rows: Row[];
  columns: string[];
  readonly: string[];
  parameters: Row[];
  parameter_columns: string[];
  level_points: string[];
  copy_rows: Row[];
  excel_sheet: string;
  dates: string[];
};
export const parameterTitles: Record<string, string> = {
  axial: "轴力参数",
  water: "水位参数",
  tilt: "测点参数",
  inclinometer: "孔号参数",
};
const geometry = [
  "钢筋直径 d（mm）",
  "钢筋根数 n（根）",
  "支撑长度 L（mm）",
  "支撑宽度 B（mm）",
];

export function EntryParameters({
  projectId,
  data,
  onClose,
  onSaved,
}: {
  projectId: string;
  data: EntryData;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const monitor = data.measurement_key.split(":")[0],
    name = data.measurement_key.split(":").slice(1).join(":");
  const [rows, setRows] = useState<Row[]>(() =>
    structuredClone(
      data.parameters.length
        ? data.parameters
        : monitor === "inclinometer"
          ? [{ 点号: name, 起始位置: "孔底", 步长: 0.5, 深度: 20 }]
          : [],
    ),
  );
  const [dirty, setDirty] = useState(false),
    [revision] = useState(data.revision),
    action = useAction();
  function close() {
    if (!action.busy && (!dirty || confirm("参数尚未保存，放弃修改？")))
      onClose();
  }
  return (
    <Modal title={parameterTitles[monitor]} onClose={close}>
      <fieldset disabled={action.busy}>
        <p className="muted">
          {monitor === "axial"
            ? "先配置点号及全部编号。钢筋计按同一点号的有效频率平均应力计算；其他传感器使用 K、初始频率和 C。修改参数会重新计算该测项历史轴力。"
            : monitor === "water"
              ? "配置点位及管口高程，录入页只填写水位读数和备注。修改管口高程会更新已有水位数据。"
              : monitor === "tilt"
                ? "选择同一水准测项中的两个点号，输入两点距离（m），按累计沉降差自动计算倾斜度。"
                : "配置孔号、起始位置、步长及总深度（m），按桌面版规则生成深度行。"}
        </p>
        {monitor !== "inclinometer" && (
          <Button
            onClick={() => {
              setRows([
                ...rows,
                Object.fromEntries(
                  data.parameter_columns.map((c) => [
                    c,
                    c === "传感器类型" ? "其他传感器" : "",
                  ]),
                ),
              ]);
              setDirty(true);
            }}
          >
            {monitor === "axial" ? "新增编号" : "新增参数行"}
          </Button>
        )}
        <EntryGrid
          rows={rows}
          columns={data.parameter_columns}
          labelPrefix="参数"
          allowDelete={monitor !== "inclinometer"}
          allowAdd={monitor !== "inclinometer"}
          readonly={(column, row) =>
            (monitor === "inclinometer" && column === "点号") ||
            (monitor === "axial" &&
              (row["传感器类型"] === "钢筋计"
                ? column === "轴力转换系数 C（无量纲）"
                : geometry.includes(column)))
          }
          choices={(column) =>
            column === "传感器类型"
              ? ["钢筋计", "其他传感器"]
              : column === "起始位置"
                ? ["孔底", "孔口"]
                : monitor === "tilt" && ["点号1", "点号2"].includes(column)
                  ? data.level_points
                  : undefined
          }
          onChange={(next) => {
            setRows(next);
            setDirty(true);
          }}
        />
        <Notice>{action.error}</Notice>
        <div className="modal-actions">
          <Button disabled={action.busy} onClick={close}>
            取消
          </Button>
          <Button
            kind="primary"
            busy={action.busy}
            onClick={() =>
              action.run(async () => {
                await api(
                  `/projects/${projectId}/entry/parameters`,
                  json(
                    { revision, measurement_key: data.measurement_key, rows },
                    "PUT",
                  ),
                );
                await onSaved();
                onClose();
              })
            }
          >
            保存参数
          </Button>
        </div>
      </fieldset>
    </Modal>
  );
}
