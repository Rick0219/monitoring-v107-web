import { Button } from "./Common";
export const permissionOptions = [
  ["data_entry", "数据录入"],
  ["database_data", "数据库数据"],
  ["database_charts", "数据库图表"],
  ["analysis", "智能分析"],
  ["reports", "报告生成"],
] as const;
export const allPermissions = permissionOptions.map(([key]) => key);
export function permissionNames(permissions: string[]) {
  return (
    permissionOptions
      .filter(([key]) => permissions.includes(key))
      .map(([, label]) => label)
      .join("、") || "未开放功能"
  );
}
export function PermissionPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}) {
  function change(key: string, checked: boolean) {
    const next = new Set(value);
    if (checked) next.add(key);
    else next.delete(key);
    onChange([...next]);
  }
  return (
    <fieldset className="permission-picker" disabled={disabled}>
      <legend>功能权限</legend>
      <div className="permission-presets">
        <Button
          type="button"
          onClick={() =>
            onChange(["database_data", "database_charts", "analysis"])
          }
        >
          查看与分析
        </Button>
        <Button
          type="button"
          onClick={() => onChange(["data_entry", "database_data"])}
        >
          数据编辑
        </Button>
        <Button type="button" onClick={() => onChange(["reports"])}>
          仅报告
        </Button>
        <Button type="button" onClick={() => onChange([...allPermissions])}>
          全部功能
        </Button>
      </div>
      <div className="permission-checks">
        {permissionOptions.map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={value.includes(key)}
              onChange={(e) => change(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
