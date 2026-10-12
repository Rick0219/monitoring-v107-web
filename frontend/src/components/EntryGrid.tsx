import { useState, type ClipboardEvent } from "react";
import { ClipboardPaste } from "lucide-react";
import type { Row } from "../api";
import { Button, Field, Notice } from "./Common";
import { pasteEntryRows } from "../entryPaste";
import { PageScrollTable } from "./PageScrollTable";

export function EntryGrid({
  rows,
  columns,
  onChange,
  readonly = () => false,
  choices,
  labelPrefix = "",
  allowAdd = false,
  allowDelete = false,
  filter = "",
  groupAxial = false,
}: {
  rows: Row[];
  columns: string[];
  onChange: (rows: Row[]) => void;
  readonly?: (column: string, row: Row) => boolean;
  choices?: (column: string, row: Row) => string[] | undefined;
  labelPrefix?: string;
  allowAdd?: boolean;
  allowDelete?: boolean;
  filter?: string;
  groupAxial?: boolean;
}) {
  const [page, setPage] = useState(0),
    [selected, setSelected] = useState<number[]>([]);
  const [pasteOpen, setPasteOpen] = useState(false),
    [pasteText, setPasteText] = useState(""),
    [pasteRow, setPasteRow] = useState(1),
    [pasteColumn, setPasteColumn] = useState(0),
    [pasteError, setPasteError] = useState(""),
    [pasteSuccess, setPasteSuccess] = useState("");
  const editableColumns = columns
    .map((column, index) => ({ column, index }))
    .filter(
      ({ column }) =>
        !readonly(column, rows[Math.max(0, pasteRow - 1)] || rows[0] || {}),
    );
  const canPaste = editableColumns.length > 0;
  const visible = rows
    .map((row, index) => ({ row, index }))
    .filter(({ row }) =>
      Object.values(row).some((value) => String(value ?? "").includes(filter)),
    );
  const last = Math.max(0, Math.ceil(visible.length / 100) - 1),
    active = Math.min(page, last);
  const shown = visible.slice(active * 100, (active + 1) * 100);
  function update(index: number, column: string, value: string) {
    setPasteError("");
    setPasteSuccess("");
    const next = [...rows];
    next[index] = { ...next[index], [column]: value };
    onChange(next);
  }
  function applyPaste(text: string, startRow: number, startColumn: number) {
    setPasteError("");
    setPasteSuccess("");
    try {
      if (filter) throw new Error("请先清除筛选，再批量粘贴，避免覆盖隐藏行。");
      const result = pasteEntryRows({
        text,
        rows,
        columns,
        startRow,
        startColumn,
        allowAdd,
        readonly,
        choices,
      });
      onChange(result.rows);
      setSelected([]);
      setPage(Math.floor(startRow / 100));
      setPasteSuccess(
        `已粘贴 ${result.pastedRows} 行${result.addedRows ? `，新增 ${result.addedRows} 行` : ""}。请核对后保存。`,
      );
      setPasteOpen(false);
      setPasteText("");
    } catch (error) {
      setPasteError(
        error instanceof Error ? error.message : "粘贴失败，请检查数据格式",
      );
    }
  }
  function pasteCells(
    event: ClipboardEvent,
    startRow: number,
    startColumn: number,
    isSelect = false,
  ) {
    const text = event.clipboardData.getData("text/plain");
    if (!isSelect && !/[\t\r\n]/.test(text)) return;
    event.preventDefault();
    applyPaste(text, startRow, startColumn);
  }
  return (
    <>
      {(allowDelete || canPaste) && (
        <div className="entry-grid-actions">
          {canPaste && (
            <Button
              type="button"
              onClick={() => {
                setPasteRow((shown[0]?.index || 0) + 1);
                setPasteColumn(editableColumns[0].index);
                setPasteText("");
                setPasteError("");
                setPasteSuccess("");
                setPasteOpen(true);
              }}
            >
              <ClipboardPaste size={16} />
              批量粘贴
            </Button>
          )}
          {allowDelete && (
            <Button
              type="button"
              disabled={!selected.length}
              onClick={() => {
                onChange(rows.filter((_, i) => !selected.includes(i)));
                setSelected([]);
              }}
            >
              删除选中行（{selected.length}）
            </Button>
          )}
        </div>
      )}
      {pasteOpen && (
        <div className="entry-paste-panel">
          <strong>从 Excel 或外部表格复制后，粘贴到下方</strong>
          <p>
            支持多行多列，可带本表表头；无表头时从所选列开始。空白位置保留，自动生成列不会被覆盖。
          </p>
          <div className="entry-paste-position">
            <Field label="粘贴起始行">
              <input
                type="number"
                min={1}
                max={Math.min(20000, rows.length + (allowAdd ? 1 : 0)) || 1}
                value={pasteRow}
                onChange={(event) => setPasteRow(Number(event.target.value))}
              />
            </Field>
            <Field label="粘贴起始列">
              <select
                value={pasteColumn}
                onChange={(event) => setPasteColumn(Number(event.target.value))}
              >
                {editableColumns.map(({ column, index }) => (
                  <option key={column} value={index}>
                    {column}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="待粘贴数据">
            <textarea
              autoFocus
              rows={6}
              spellCheck={false}
              value={pasteText}
              placeholder="在这里按 Ctrl+V 粘贴，可以一次粘贴整行或多行数据"
              onChange={(event) => {
                setPasteText(event.target.value);
                setPasteError("");
              }}
            />
          </Field>
          <div className="toolbar-group">
            <Button
              type="button"
              kind="primary"
              onClick={() => applyPaste(pasteText, pasteRow - 1, pasteColumn)}
            >
              应用粘贴
            </Button>
            <Button
              type="button"
              onClick={() => {
                setPasteOpen(false);
                setPasteError("");
              }}
            >
              取消粘贴
            </Button>
          </div>
        </div>
      )}
      <Notice>{pasteError}</Notice>
      <Notice success>{pasteSuccess}</Notice>
      <div className="data-table entry-grid">
        <PageScrollTable
          label={labelPrefix ? `${labelPrefix}表格` : "单期录入表"}
        >
          <table>
            <thead>
              <tr>
                <th>行</th>
                {allowDelete && <th>选择</th>}
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map(({ row, index }, position) => (
                <tr key={index}>
                  <td>{index + 1}</td>
                  {allowDelete && (
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${labelPrefix}选择第${index + 1}行`}
                        checked={selected.includes(index)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, index]
                              : selected.filter((i) => i !== index),
                          )
                        }
                      />
                    </td>
                  )}
                  {columns.map((column, columnIndex) => {
                    const grouped =
                      groupAxial && ["点号", "轴力（kN）"].includes(column);
                    if (
                      grouped &&
                      position > 0 &&
                      shown[position - 1].row["点号"] === row["点号"]
                    )
                      return null;
                    let span = 1;
                    if (grouped)
                      while (
                        position + span < shown.length &&
                        shown[position + span].row["点号"] === row["点号"]
                      )
                        span++;
                    const locked = readonly(column, row),
                      options = choices?.(column, row);
                    const label = `${labelPrefix}第${index + 1}行 ${column}`;
                    return (
                      <td
                        key={column}
                        rowSpan={span}
                        className={locked ? "entry-readonly" : ""}
                      >
                        {options && !locked ? (
                          <select
                            aria-label={label}
                            value={String(row[column] ?? "")}
                            onChange={(e) =>
                              update(index, column, e.target.value)
                            }
                            onPaste={(event) =>
                              pasteCells(event, index, columnIndex, true)
                            }
                          >
                            <option value="">请选择</option>
                            {options.map((value) => (
                              <option key={value}>{value}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            aria-label={label}
                            readOnly={locked}
                            value={row[column] ?? ""}
                            onChange={(e) =>
                              update(index, column, e.target.value)
                            }
                            onPaste={(event) =>
                              pasteCells(event, index, columnIndex)
                            }
                          />
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </PageScrollTable>
      </div>
      <div className="database-pagination">
        <span>
          共 {visible.length} 行 · 第 {active + 1} / {last + 1} 页
        </span>
        <Button disabled={!active} onClick={() => setPage(active - 1)}>
          上一页
        </Button>
        <Button disabled={active === last} onClick={() => setPage(active + 1)}>
          下一页
        </Button>
      </div>
    </>
  );
}
