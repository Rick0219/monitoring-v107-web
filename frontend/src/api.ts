import { rememberLoginDestination } from "./authNavigation";
export type User = {
  id: string;
  email: string;
  full_name: string;
  is_superuser: boolean;
  is_active: boolean;
  permissions: string[];
};
export type Project = {
  id: string;
  name: string;
  description: string;
  location: string;
  owner_id: string;
  owner_name: string;
  revision: number;
  measurement_count: number;
  row_count: number;
  updated_at: string;
  permissions: string[];
};
export type Row = Record<string, string | number | null>;
export type DataSet = {
  entry_sets?: string[];
  revision: number;
  measurements: Record<string, Row[]>;
  catalog: { key: string; label: string; dates: string[]; points: string[] }[];
  types: {
    key: string;
    name: string;
    description: string;
    columns: string[];
  }[];
};
export type Scope = {
  measurement_key: string;
  start_date: string;
  end_date: string;
  point: string;
};
export type Analysis = {
  data_name: string;
  columns: string[];
  rows: Row[];
  summary: Record<string, any>;
  warnings: string[];
  series: {
    point: string;
    unit: string;
    measurement_key?: string;
    measurement_name?: string;
    values: { date: string; value: number | null }[];
  }[];
};
export type TwinPoint = {
  id: string;
  measurement_key: string;
  point: string;
  position: [number, number] | null;
  elevation?: number;
  visible?: boolean;
};
export type TwinScene = {
  schema_version: number;
  scene_id?: string;
  project?: { id?: string; name?: string; revision_at_export?: number };
  source?: Record<string, unknown>;
  coordinate_system?: { kind?: string; axis?: string; bounds?: number[]; width_native?: number; height_native?: number };
  layers: { id: string; name: string; visible?: boolean; locked?: boolean; color_index?: number }[];
  objects: { id: string; layer_id?: string; source_type?: string; height?: number; geometry: Record<string, any> }[];
  placed_points: TwinPoint[];
  /** Legacy DWG recognition data may be present in an old file; the web UI ignores it. */
  sensors?: TwinPoint[];
};
export type DocumentInfo = {
  id: string;
  name: string;
  status: string;
  chunk_count: number;
  summary: string;
  error: string;
  parser: string;
};
export const token = () => sessionStorage.getItem("monitoring_token");
export async function request(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token()) headers.set("Authorization", "Bearer " + token());
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !(init.body instanceof URLSearchParams)
  )
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api/v1" + path, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401 && !path.includes("/login/")) {
      rememberLoginDestination();
      sessionStorage.removeItem("monitoring_token");
      window.location.assign("/login");
    }
    let detail: any;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = "服务暂时不可用";
    }
    throw new Error(
      Array.isArray(detail)
        ? detail.map((d: any) => d.msg).join("；")
        : String(detail || "操作失败"),
    );
  }
  return response;
}
export async function api<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return (await request(path, init)).json();
}
export const json = (body: unknown, method = "POST"): RequestInit => ({
  method,
  body: JSON.stringify(body),
});
export async function download(path: string, filename: string, body?: unknown) {
  const response = await request(path, body ? json(body) : {});
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
export function saveText(text: string, filename: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
