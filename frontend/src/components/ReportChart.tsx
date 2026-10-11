import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  AriaComponent,
  MarkLineComponent,
  TitleComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ChartData } from "../pages/ProjectDatabase";
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  AriaComponent,
  MarkLineComponent,
  TitleComponent,
  CanvasRenderer,
]);

export function buildReportChartOption(data: ChartData) {
  const byPoint = new Map(data.points.map((point) => [point.point, point]));
  const selected = data.selected_points
    .map((point) => byPoint.get(point)!)
    .filter(Boolean);
  const history = data.settings.display === "history",
    profile = data.monitor === "inclinometer";
  const category = {
    type: "category",
    axisLabel: { color: "#64748b", hideOverlap: true },
    axisLine: { lineStyle: { color: "#cbd5e1" } },
    axisTick: { alignWithLabel: true },
  };
  const numeric = {
    type: "value",
    nameLocation: "middle",
    nameGap: 48,
    axisLabel: { color: "#64748b" },
    splitLine: { lineStyle: { color: "#e9eef3", type: "dashed" } },
  };
  let series: any[], xAxis: any, yAxis: any;
  if (profile) {
    const byDepth = [...selected].sort((a, b) => a.depth! - b.depth!);
    xAxis = {
      ...numeric,
      name: `累计位移（${data.unit}）`,
      position: "top",
      nameGap: 30,
    };
    yAxis = { ...numeric, name: "深度（m）", inverse: true, min: 0 };
    series = history
      ? data.history_dates.map((date) => ({
          name: date,
          type: "line",
          symbolSize: 6,
          connectNulls: false,
          data: byDepth.map((p) => [
            p.values.find((v) => v.date === date)?.value ?? null,
            p.depth,
          ]),
        }))
      : [
          {
            name: "初始值",
            type: "line",
            symbol: "none",
            lineStyle: { type: "dashed", color: "#94a3b8" },
            data: byDepth.map((p) => [0, p.depth]),
          },
          {
            name: data.effective_date,
            type: "line",
            symbolSize: 6,
            connectNulls: false,
            data: byDepth.map((p) => [p.current, p.depth]),
          },
        ];
  } else if (history) {
    xAxis = {
      ...category,
      name: "监测日期",
      nameLocation: "middle",
      nameGap: 35,
      data: data.history_dates,
    };
    yAxis = { ...numeric, name: `累计值（${data.unit}）` };
    const dateIndex = new Map(
      data.history_dates.map((date, index) => [date, index]),
    );
    series = selected.map((p) => {
      // Retain gaps without allocating a points × dates matrix for sparse data.
      const values: [string, number | null][] = [];
      let previous = -1;
      for (const value of p.values) {
        const index = dateIndex.get(value.date);
        if (index === undefined) continue;
        if (index > previous + 1)
          values.push([data.history_dates[previous + 1], null]);
        values.push([value.date, value.value]);
        previous = index;
      }
      return {
        name: p.point,
        type: "line",
        showSymbol: data.history_dates.length < 50,
        symbolSize: 5,
        connectNulls: false,
        data: values,
      };
    });
  } else {
    xAxis = {
      ...category,
      name: "监测点号",
      nameLocation: "middle",
      nameGap: 35,
      data: selected.map((p) => p.point),
    };
    yAxis = { ...numeric, name: `累计值（${data.unit}）` };
    series = [
      {
        name: "本次累计值",
        type: data.settings.display === "bar" ? "bar" : "line",
        barMaxWidth: 40,
        symbolSize: 6,
        connectNulls: false,
        data: selected.map((p) => p.current),
      },
    ];
  }
  const bounds = (data.control_bounds || []).filter(
    (v): v is number => v !== null,
  );
  if (bounds.length && series.length) {
    series[series.length - 1].markLine = {
      silent: true,
      symbol: "none",
      lineStyle: { color: "#d97757", type: "dashed" },
      label: { position: "insideEndTop", formatter: "控制值 {c}" },
      data: bounds.map((value) =>
        profile ? { xAxis: value } : { yAxis: value },
      ),
    };
    const numericAxis = profile ? xAxis : yAxis;
    numericAxis.min = (extent: { min: number }) =>
      Math.min(extent.min, ...bounds);
    numericAxis.max = (extent: { max: number }) =>
      Math.max(extent.max, ...bounds);
  }
  return {
    title: {
      text: `${data.label}监测变化图`,
      subtext: data.effective_date,
      left: 12,
      top: 0,
      textStyle: { fontSize: 12, color: "#334155" },
      subtextStyle: { fontSize: 11 },
    },
    color: [
      "#16878b",
      "#4f78c4",
      "#d39a38",
      "#a071bd",
      "#dc7272",
      "#4e9980",
      "#6e90a9",
      "#b18550",
      "#96708c",
      "#687d38",
    ],
    backgroundColor: "#ffffff",
    animation: false,
    aria: { enabled: true },
    grid: { left: 78, right: 36, top: profile ? 90 : 65, bottom: 110 },
    tooltip: {
      trigger: profile ? "item" : "axis",
      triggerOn: "mousemove|click",
      renderMode: "richText",
      confine: true,
      ...(profile
        ? {
            formatter: (params: any) => {
              const value = params.value as [number | null, number];
              return `${params.seriesName}\n深度：${value[1]} m\n累计位移：${value[0] == null ? "缺测" : value[0] + " " + data.unit}`;
            },
          }
        : {}),
      valueFormatter: (value: unknown) =>
        value == null ? "缺测" : String(value),
    },
    legend: { type: "scroll", bottom: 4, left: 20, right: 20 },
    toolbox: {
      right: 12,
      top: 0,
      feature: {
        saveAsImage: {
          title: "下载图片",
          name: `${data.label}-${data.effective_date}`,
          pixelRatio: 2,
        },
        restore: { title: "重置缩放" },
      },
    },
    dataZoom: profile
      ? []
      : [
          { type: "inside", xAxisIndex: 0, zoomOnMouseWheel: "ctrl" },
          {
            type: "slider",
            xAxisIndex: 0,
            bottom: 46,
            height: 18,
            borderColor: "#e1e8ef",
          },
        ],
    xAxis,
    yAxis,
    series,
  };
}
export default function ReportChart({ data }: { data: ChartData }) {
  const ref = useRef<HTMLDivElement>(null);
  const option = useMemo(() => buildReportChartOption(data), [data]);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option]);
  return (
    <div
      ref={ref}
      className="report-chart"
      role="img"
      aria-label={`${data.label}，${data.selected_points.length} 个点位，${data.effective_date}`}
    />
  );
}
