import { test, expect } from "@playwright/test";
import * as report from "../src/components/ReportChart";

function profile(display = "history") {
  return {
    label: "深层水平位移 · CX01",
    monitor: "inclinometer",
    unit: "mm",
    effective_date: "2026-01-05",
    settings: { display },
    selected_points: ["10", "1", "5"],
    control_bounds: [-50, 50],
    history_dates: ["2026-01-01", "2026-01-03", "2026-01-05"],
    points: [
      {
        point: "10",
        depth: 10,
        current: 6,
        values: [
          { date: "2026-01-01", value: 0 },
          { date: "2026-01-03", value: 3 },
          { date: "2026-01-05", value: 6 },
        ],
      },
      {
        point: "1",
        depth: 1,
        current: -2,
        values: [
          { date: "2026-01-01", value: 0 },
          { date: "2026-01-03", value: -1 },
          { date: "2026-01-05", value: -2 },
        ],
      },
      {
        point: "5",
        depth: 5,
        current: null,
        values: [
          { date: "2026-01-01", value: 0 },
          { date: "2026-01-03", value: 4 },
        ],
      },
    ],
  };
}
test("测斜历史曲线按日期叠加剖面，保留深度顺序与缺测", () => {
  const build = (report as any).buildReportChartOption;
  expect(typeof build).toBe("function");
  const option = build(profile());
  expect(option.xAxis.name).toContain("累计位移");
  expect(option.yAxis.name).toContain("深度");
  expect(option.yAxis.inverse).toBe(true);
  const curves = option.series.filter((s: any) => /^2026/.test(s.name));
  expect(curves.map((s: any) => s.name)).toEqual([
    "2026-01-01",
    "2026-01-03",
    "2026-01-05",
  ]);
  expect(curves[1].data).toEqual([
    [-1, 1],
    [4, 5],
    [3, 10],
  ]);
  expect(curves[2].data).toEqual([
    [-2, 1],
    [null, 5],
    [6, 10],
  ]);
  expect(curves[2].connectNulls).toBe(false);
  expect(curves[2].markLine.data).toEqual([{ xAxis: -50 }, { xAxis: 50 }]);
});
test("测斜提示同时给出所属日期、深度和带符号累计位移", () => {
  const build = (report as any).buildReportChartOption;
  expect(typeof build).toBe("function");
  const option = build(profile("daily"));
  const tip = option.tooltip.formatter({
    seriesName: "2026-01-05",
    value: [-2, 1],
  });
  expect(tip).toContain("2026-01-05");
  expect(tip).toContain("深度：1 m");
  expect(tip).toContain("累计位移：-2 mm");
  expect(option.tooltip.triggerOn).toContain("click");
});
