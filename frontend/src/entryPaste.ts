import type { Row } from "./api";

const MAX_ROWS = 20000;

/** Excel clipboard TSV: retain empty cells/rows and quoted multiline remarks. */
export function parseClipboard(text: string): string[][] {
  if (!text.trim()) throw new Error("请先粘贴数据");
  if (text.length > 5_000_000) throw new Error("粘贴内容过大，请分批粘贴");
  const records: string[][] = [];
  let row: string[] = [],
    cell = "",
    quoted = false;
  text = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  function finishRow() {
    row.push(cell.trim());
    records.push(row);
    if (records.length > MAX_ROWS + 1) throw new Error("一次最多粘贴 20000 行");
    row = [];
    cell = "";
  }
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"' && (quoted || !cell)) {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (char === "\t" && !quoted) {
      row.push(cell.trim());
      cell = "";
      if (row.length > 256)
        throw new Error("粘贴列数过多，请只复制本表需要的列");
    } else if (char === "\n" && !quoted) finishRow();
    else cell += char;
  }
  if (quoted) throw new Error("粘贴内容的引号未闭合，请重新复制完整单元格");
  if (cell || row.length) finishRow();
  // A terminal newline was already consumed; any remaining empty row is real data.
  if (!records.length) throw new Error("请先粘贴数据");
  return records;
}

type PasteOptions = {
  text: string;
  rows: Row[];
  columns: string[];
  startRow?: number;
  startColumn?: number;
  allowAdd?: boolean;
  readonly?: (column: string, row: Row) => boolean;
  choices?: (column: string, row: Row) => string[] | undefined;
};

export function pasteEntryRows({
  text,
  rows,
  columns,
  startRow = 0,
  startColumn = 0,
  allowAdd = false,
  readonly = () => false,
  choices,
}: PasteOptions) {
  if (!Number.isInteger(startRow) || startRow < 0 || startRow > rows.length)
    throw new Error("起始行须为已有行或表格末尾的下一行");
  if (
    !Number.isInteger(startColumn) ||
    startColumn < 0 ||
    startColumn >= columns.length
  )
    throw new Error("请选择有效的起始列");
  const records = parseClipboard(text);
  const headerKey = (value: string) =>
    value.replace(/\s/g, "").replace(/（/g, "(").replace(/）/g, ")");
  const headers = records[0].map((value) =>
    columns.find((column) => headerKey(column) === headerKey(value)),
  );
  let mapped: string[] | undefined;
  if (headers.every(Boolean)) {
    mapped = headers as string[];
    if (new Set(mapped).size !== mapped.length)
      throw new Error("粘贴表头存在重复列");
    records.shift();
  } else if (headers.filter(Boolean).length >= 2) {
    throw new Error(
      "部分表头无法识别，请使用与录入表一致的列名，或只复制数据行",
    );
  }
  if (!records.length) throw new Error("只有表头，没有可粘贴的数据行");
  if (startRow + records.length > MAX_ROWS)
    throw new Error("录入表最多支持 20000 行，请分批处理");
  if (!allowAdd && startRow + records.length > rows.length)
    throw new Error(
      "粘贴行数超过当前表格，请先配置参数或新增点位，再按表格顺序粘贴",
    );

  const width = Math.max(...records.map((row) => row.length));
  if (!mapped) {
    const remainder = columns.slice(startColumn);
    if (width === columns.length) mapped = columns;
    else if (width === remainder.length) mapped = remainder;
    else
      mapped = remainder.filter(
        (column) => !readonly(column, rows[startRow] || {}),
      );
  }
  if (width > mapped.length)
    throw new Error("粘贴列数超出可填写范围，请检查起始列或复制范围");

  const next = rows.map((row) => ({ ...row }));
  let editedCells = 0;
  records.forEach((values, offset) => {
    const at = startRow + offset;
    next[at] ||= Object.fromEntries(columns.map((column) => [column, ""]));
    // Evaluate dependent parameter fields against the proposed row,
    // regardless of the order in which clipboard headers were copied.
    const proposed = {
      ...next[at],
      ...Object.fromEntries(values.map((value, col) => [mapped![col], value])),
    };
    values.forEach((value, col) => {
      const column = mapped![col];
      if (readonly(column, proposed)) {
        if (
          ["点号", "编号", "点位"].includes(column) &&
          value &&
          value !== String(next[at][column] ?? "").trim()
        )
          throw new Error(
            `第 ${at + 1} 行${column}与当前表格不一致，请按点位顺序重新复制`,
          );
        return;
      }
      const options = choices?.(column, proposed);
      if (options && value && !options.includes(value))
        throw new Error(`第 ${at + 1} 行${column}“${value}”不是可选值`);
      next[at][column] = value;
      editedCells++;
    });
  });
  if (!editedCells)
    throw new Error("粘贴范围内没有可编辑列，自动计算列无需填写");
  return {
    rows: next,
    pastedRows: records.length,
    addedRows: next.length - rows.length,
    editedCells,
  };
}
