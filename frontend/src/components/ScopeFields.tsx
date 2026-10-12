import type { DataSet, Scope } from "../api";
import { Field } from "./Common";
export function initialScope(data: DataSet): Scope {
  const dates = data.catalog.flatMap((c) => c.dates).sort();
  return {
    measurement_key: "__all__",
    start_date: dates[0] || "",
    end_date: dates.at(-1) || "",
    point: "",
  };
}
export function ScopeFields({
  data,
  scope,
  setScope,
}: {
  data: DataSet;
  scope: Scope;
  setScope: (s: Scope) => void;
}) {
  const item = data.catalog.find((c) => c.key === scope.measurement_key);
  return (
    <>
      <Field label="分析测项">
        <select
          value={scope.measurement_key}
          onChange={(e) =>
            setScope({ ...scope, measurement_key: e.target.value, point: "" })
          }
        >
          <option value="__all__">综合分析 · 全部测项及点位</option>
          {data.catalog.map((c) => (
            <option key={c.key} value={c.key}>
              {c.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="点位 / 深度">
        <select
          value={scope.point}
          disabled={!item}
          onChange={(e) => setScope({ ...scope, point: e.target.value })}
        >
          <option value="">全部点位</option>
          {item?.points.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </Field>
      <div className="date-grid">
        <Field label="开始日期">
          <input
            type="date"
            value={scope.start_date}
            onChange={(e) => setScope({ ...scope, start_date: e.target.value })}
          />
        </Field>
        <Field label="结束日期">
          <input
            type="date"
            value={scope.end_date}
            onChange={(e) => setScope({ ...scope, end_date: e.target.value })}
          />
        </Field>
      </div>
    </>
  );
}
