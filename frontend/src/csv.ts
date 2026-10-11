import type { Row } from "./api";
export function parseCSV(text: string): Row[] {
  const records: string[][] = [];
  let row: string[] = [],
    cell = "",
    quoted = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (c === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((c === "\n" || c === "\r") && !quoted) {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      if (row.some((v) => v.trim())) records.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  if (quoted) throw new Error("CSV 引号未闭合");
  row.push(cell);
  if (row.some((v) => v.trim())) records.push(row);
  const headers = records.shift()?.map((h) => h.trim());
  if (!headers?.length || new Set(headers).size !== headers.length)
    throw new Error("CSV 表头为空或存在重复列");
  return records.map((r, i) => {
    if (r.length !== headers.length)
      throw new Error("CSV 第 " + (i + 2) + " 行列数与表头不一致");
    return Object.fromEntries(headers.map((h, j) => [h, r[j]]));
  });
}
export function toCSV(rows: Row[], columns: string[]): string {
  const cell = (v: any) => {
    let s = String(v ?? "");
    if (/^[=+@-]/.test(s.trimStart())) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"';
  };
  return (
    "\uFEFF" +
    [columns, ...rows.map((r) => columns.map((c) => r[c]))]
      .map((r) => r.map(cell).join(","))
      .join("\r\n")
  );
}
