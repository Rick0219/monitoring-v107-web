import { test, expect } from "@playwright/test";
import { parseClipboard, pasteEntryRows } from "../src/entryPaste";

test("保留中间空行、空单元格及 Excel 引号内换行", () => {
  expect(
    parseClipboard(
      'A\t1\t"第一行\n第二行"\r\nB\t\t\r\n\t\t\r\nC\t-3\t"含""引号"\r\n',
    ),
  ).toEqual([
    ["A", "1", "第一行\n第二行"],
    ["B", "", ""],
    ["", "", ""],
    ["C", "-3", '含"引号'],
  ]);
  expect(() => parseClipboard('A\t"未闭合')).toThrow("引号");
  expect(parseClipboard("1\n\n")).toEqual([["1"], [""]]);
});

test("单列测值保留空行并自动补行，其他列保持", () => {
  const rows = [
    { 深度: ".5", 测值: "旧值" },
    { 深度: "1", 测值: "旧值" },
  ];
  const result = pasteEntryRows({
    text: "1\n\n3\n",
    rows,
    columns: ["深度", "测值"],
    startColumn: 1,
    allowAdd: true,
  });
  expect(result.rows).toEqual([
    { 深度: ".5", 测值: "1" },
    { 深度: "1", 测值: "" },
    { 深度: "", 测值: "3" },
  ]);
  expect(result.addedRows).toBe(1);
  expect(rows[0].测值).toBe("旧值");
});

test("完整表头按名称匹配，日期和计算列保持只读", () => {
  const result = pasteEntryRows({
    text: "备注\t点号\t时间\t测量值\n正常\tA\t旧日期\t10",
    rows: [{ 时间: "当前期", 点号: "A", 测量值: "9" }],
    columns: ["时间", "点号", "测量值", "备注"],
    readonly: (c) => c === "时间",
    startColumn: 2,
  });
  expect(result.rows[0]).toEqual({
    时间: "当前期",
    点号: "A",
    测量值: "10",
    备注: "正常",
  });
  expect(() =>
    pasteEntryRows({
      text: "点号\t点号\nA\tB",
      rows: [],
      columns: ["点号"],
      allowAdd: true,
    }),
  ).toThrow("重复");
});

test("含只读轴力的整行按位置跳过，点号编号不匹配则整批拒绝", () => {
  const rows = [
    {
      时间: "当前期",
      点号: "Z1",
      编号: "1",
      频率: "1000",
      "轴力（kN）": "0",
      备注: "",
    },
  ];
  const columns = Object.keys(rows[0]);
  const readonly = (c: string) => !["频率", "备注"].includes(c);
  const result = pasteEntryRows({
    text: "旧日期\tZ1\t1\t1100\t999\t复测",
    rows,
    columns,
    readonly,
    startColumn: 3,
  });
  expect(result.rows[0]).toEqual({ ...rows[0], 频率: "1100", 备注: "复测" });
  expect(() =>
    pasteEntryRows({
      text: "旧日期\tZ2\t1\t1200\t999\t错误",
      rows,
      columns,
      readonly,
    }),
  ).toThrow("点号");
  expect(rows[0].频率).toBe("1000");
});

test("固定参数行超出范围、列数超出、行数上限不静默截断", () => {
  const options = { rows: [{ 测值: "1" }], columns: ["测值"] };
  expect(() => pasteEntryRows({ ...options, text: "2\n3" })).toThrow("行数");
  expect(() => pasteEntryRows({ ...options, text: "2\t3" })).toThrow("列数");
  expect(() =>
    pasteEntryRows({ ...options, text: "2", startRow: 2, allowAdd: true }),
  ).toThrow("起始行");
  expect(() =>
    pasteEntryRows({ ...options, text: "2\n".repeat(20001), allowAdd: true }),
  ).toThrow("20000");
  expect(options.rows).toEqual([{ 测值: "1" }]);
});

test("参数下拉选项参与验证，不能粘贴不存在的传感器类型", () => {
  expect(() =>
    pasteEntryRows({
      text: "错误类型",
      rows: [],
      columns: ["传感器类型"],
      allowAdd: true,
      choices: () => ["钢筋计", "其他传感器"],
    }),
  ).toThrow("传感器类型");
  const result = pasteEntryRows({
    text: "钢筋直径\t传感器类型\n20\t钢筋计",
    rows: [{ 传感器类型: "其他传感器", 钢筋直径: "" }],
    columns: ["传感器类型", "钢筋直径"],
    readonly: (column, row) =>
      column === "钢筋直径" && row["传感器类型"] !== "钢筋计",
  });
  expect(result.rows[0]).toEqual({ 传感器类型: "钢筋计", 钢筋直径: "20" });
});
