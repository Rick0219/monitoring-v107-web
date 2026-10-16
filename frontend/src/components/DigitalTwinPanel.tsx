import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Eye,
  EyeOff,
  FileUp,
  MousePointer2,
  Plus,
  RotateCcw,
  RotateCw,
  Save,
  Settings2,
  Trash2,
  Upload,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api, json, type DataSet, type Project, type Scope, type TwinPoint, type TwinScene } from "../api";
import type { ChartData } from "../pages/ProjectDatabase";
import { Button, Empty, Modal, Notice, useAction } from "./Common";

const ReportChart = lazy(() => import("./ReportChart"));

type Props = { project: Project; data: DataSet; scope: Scope; setScope: (scope: Scope) => void };
type Camera = { yaw: number; pitch: number; zoom: number };
type DatabasePoint = { key: string; measurement_key: string; point: string; label: string };
type DragOrigin = { x: number; y: number };

const PALETTE = ["#3b7588", "#1e8b83", "#8a6a37", "#8064a2", "#a35555", "#4774a6"];
const POINT_MIN = -2;
const POINT_MAX = 2;

function cleanScene(value: TwinScene): TwinScene {
  const { sensors: _sensors, sensor_binding_rules: _rules, recognition: _recognition, ...scene } = value as TwinScene & { sensor_binding_rules?: unknown; recognition?: unknown };
  return { ...scene, placed_points: Array.isArray(value.placed_points) ? value.placed_points : [] };
}

function layerHeight(name: string) {
  if (/连续墙|围护|挡墙|墙/.test(name)) return 0.52;
  if (/支撑/.test(name)) return 0.34;
  if (/冠梁/.test(name)) return 0.4;
  if (/围檩/.test(name)) return 0.28;
  if (/结构|底板|楼板/.test(name)) return 0.2;
  return 0.13;
}

function nativePoint(value: number[]) {
  return [Math.max(0, Math.min(1, Number(value[0]) || 0)), Math.max(0, Math.min(1, Number(value[1]) || 0))] as [number, number];
}

function projectPoint(point: [number, number], z: number, camera: Camera) {
  const x = point[0] - 0.5;
  const y = point[1] - 0.5;
  const cos = Math.cos(camera.yaw);
  const sin = Math.sin(camera.yaw);
  const rx = x * cos - y * sin;
  const ry = x * sin + y * cos;
  const scale = 58 * camera.zoom;
  return [50 + (rx - ry) * scale, 43 + (rx + ry) * scale * camera.pitch - z * 22 * camera.zoom] as [number, number];
}

function pointString(points: [number, number][]) {
  return points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
}

function inverseScenePoint(event: { currentTarget: SVGSVGElement; clientX: number; clientY: number }, camera: Camera) {
  const rect = event.currentTarget.getBoundingClientRect();
  const sx = ((event.clientX - rect.left) / rect.width) * 100;
  const sy = ((event.clientY - rect.top) / rect.height) * 80;
  const scale = 58 * camera.zoom;
  const u = (sx - 50) / scale;
  const v = (sy - 43) / (scale * camera.pitch);
  const rx = (u + v) / 2;
  const ry = (v - u) / 2;
  const cos = Math.cos(camera.yaw);
  const sin = Math.sin(camera.yaw);
  // Keep the placement canvas larger than the normalized structural geometry,
  // so points can be placed around the pit as well as inside it.
  return [Math.max(POINT_MIN, Math.min(POINT_MAX, rx * cos + ry * sin + 0.5)), Math.max(POINT_MIN, Math.min(POINT_MAX, -rx * sin + ry * cos + 0.5))] as [number, number];
}

function Prism({ points, closed, stroke, height, camera }: { points: [number, number][]; closed: boolean; stroke: string; height: number; camera: Camera }) {
  if (points.length < 2) return null;
  const base = points.map((point) => projectPoint(point, 0, camera));
  const top = points.map((point) => projectPoint(point, height, camera));
  const edges = points.slice(0, -1).map((_, index) => [index, index + 1] as const);
  if (closed) edges.push([points.length - 1, 0]);
  return (
    <g>
      {edges.map(([a, b]) => <polygon key={`side-${a}-${b}`} points={pointString([base[a], base[b], top[b], top[a]])} fill={stroke} opacity="0.16" stroke={stroke} strokeWidth="0.12" />)}
      {closed ? <polygon points={pointString(top)} fill={`${stroke}28`} stroke={stroke} strokeWidth="0.22" /> : <polyline points={pointString(top)} fill="none" stroke={stroke} strokeWidth="0.24" />}
      <polyline points={pointString(base)} fill="none" stroke={stroke} strokeWidth="0.12" opacity="0.34" />
    </g>
  );
}

function circlePoints(center: [number, number], radius: number) {
  return Array.from({ length: 20 }, (_, index) => {
    const angle = (index / 20) * Math.PI * 2;
    return nativePoint([center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius]);
  });
}

function Geometry3D({ geometry, stroke, height, camera }: { geometry: Record<string, any>; stroke: string; height: number; camera: Camera }) {
  if (geometry.kind === "circle") return <Prism points={circlePoints(nativePoint(geometry.center), Number(geometry.radius) || 0.01)} closed stroke={stroke} height={height} camera={camera} />;
  if (geometry.kind === "hatch") return <>{(geometry.polygons || []).map((points: number[][], index: number) => <Prism key={index} points={points.map(nativePoint)} closed stroke={stroke} height={height} camera={camera} />)}</>;
  if (geometry.kind === "line" || geometry.kind === "polyline") return <Prism points={(geometry.points || []).map(nativePoint)} closed={Boolean(geometry.closed)} stroke={stroke} height={height} camera={camera} />;
  return null;
}

function pointKey(measurementKey: string, point: string) {
  return `${measurementKey}::${point}`;
}

function pointId(measurementKey: string, point: string) {
  return `point:${encodeURIComponent(measurementKey)}:${encodeURIComponent(point)}`;
}

export function DigitalTwinPanel({ project, data, scope, setScope }: Props) {
  const base = "/projects/" + project.id;
  const fileRef = useRef<HTMLInputElement>(null);
  const dwgFileRef = useRef<HTMLInputElement>(null);
  const viewMoved = useRef(false);
  const action = useAction();
  const [scene, setScene] = useState<TwinScene | null>(null);
  const [revision, setRevision] = useState(project.revision);
  const [dirty, setDirty] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeDbKey, setActiveDbKey] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [viewDrag, setViewDrag] = useState<DragOrigin | null>(null);
  const [visibleLayers, setVisibleLayers] = useState<Record<string, boolean>>({});
  const [configOpen, setConfigOpen] = useState(false);
  const [camera, setCamera] = useState<Camera>({ yaw: -0.34, pitch: 0.46, zoom: 1 });
  const [pointChart, setPointChart] = useState<ChartData | null>(null);
  const [chartError, setChartError] = useState("");
  const [chartLoading, setChartLoading] = useState(false);
  const canEdit = project.permissions.includes("data_entry");

  useEffect(() => {
    let cancelled = false;
    void api<{ scene: TwinScene | null; revision: number }>(base + "/twin/scene")
      .then((result) => {
        if (cancelled) return;
        const next = result.scene ? cleanScene(result.scene) : null;
        setScene(next);
        setRevision(result.revision);
        if (next) setVisibleLayers(Object.fromEntries(next.layers.map((layer) => [layer.id, layer.visible !== false])));
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [base]);

  const databasePoints = useMemo<DatabasePoint[]>(() => data.catalog.flatMap((item) => item.points.map((point) => ({ key: pointKey(item.key, point), measurement_key: item.key, point, label: item.label }))), [data.catalog]);
  const placed = scene?.placed_points || [];
  const placedKeys = useMemo(() => new Set(placed.map((item) => pointKey(item.measurement_key, item.point))), [placed]);
  const available = databasePoints.filter((item) => !placedKeys.has(item.key));
  const selected = placed.find((item) => item.id === activeId) || null;
  const selectedDb = databasePoints.find((item) => item.key === (selected ? pointKey(selected.measurement_key, selected.point) : activeDbKey)) || databasePoints[0] || null;
  const selectedMeasurement = selectedDb?.measurement_key || databasePoints[0]?.measurement_key || "";
  const selectedPoint = selectedDb?.point || databasePoints.find((item) => item.measurement_key === selectedMeasurement)?.point || "";

  function selectDatabasePoint(item: DatabasePoint) {
    const existing = placed.find((entry) => pointKey(entry.measurement_key, entry.point) === item.key);
    setScope({ ...scope, measurement_key: item.measurement_key, point: item.point });
    setActiveDbKey(item.key);
    setActiveId(existing?.id || null);
  }

  function setPointPosition(id: string, position: [number, number]) {
    setScene((current) => current ? ({ ...current, placed_points: current.placed_points.map((entry) => entry.id === id ? { ...entry, position } : entry) }) : current);
    setDirty(true);
  }

  function addSelectedPoint(position: [number, number] = [0.5, 0.5]) {
    if (!scene || !selectedDb || placedKeys.has(selectedDb.key)) return;
    const next: TwinPoint = { id: pointId(selectedDb.measurement_key, selectedDb.point), measurement_key: selectedDb.measurement_key, point: selectedDb.point, position, elevation: 0.18, visible: true };
    setScene({ ...scene, placed_points: [...scene.placed_points, next] });
    setActiveId(next.id);
    setActiveDbKey(selectedDb.key);
    setScope({ ...scope, measurement_key: next.measurement_key, point: next.point });
    setDirty(true);
  }

  function removeSelectedPoint() {
    if (!scene || !selected) return;
    setScene({ ...scene, placed_points: scene.placed_points.filter((entry) => entry.id !== selected.id) });
    setActiveId(null);
    setDirty(true);
  }

  async function showPointChart(item: DatabasePoint) {
    selectDatabasePoint(item);
    setChartError("");
    setChartLoading(true);
    try {
      const result = await api<ChartData>(`${base}/charts?measurement_key=${encodeURIComponent(item.measurement_key)}`);
      if (!result.points.some((point) => point.point === item.point)) throw new Error("该点暂无可绘制数据");
      setPointChart({ ...result, settings: { ...result.settings, mode: "custom", points: [item.point] }, selected_points: [item.point] });
    } catch (error) {
      setPointChart(null);
      setChartError(error instanceof Error ? error.message : "读取点位图表失败");
    } finally {
      setChartLoading(false);
    }
  }

  async function importScene(file: File) {
    const form = new FormData();
    form.append("file", file);
    const result = await api<{ scene: TwinScene; revision: number }>(base + "/twin/import", { method: "POST", body: form });
    const next = cleanScene(result.scene);
    setScene(next);
    setRevision(result.revision);
    setVisibleLayers(Object.fromEntries(next.layers.map((layer) => [layer.id, layer.visible !== false])));
    setActiveId(null);
    setActiveDbKey(null);
    setDirty(false);
  }

  async function previewDwg(file: File) {
    const form = new FormData();
    form.append("file", file);
    const result = await api<{ scene: TwinScene; revision: number }>(base + "/twin/dwg-preview", { method: "POST", body: form });
    const next = cleanScene(result.scene);
    setScene(next);
    setRevision(result.revision);
    setVisibleLayers(Object.fromEntries(next.layers.map((layer) => [layer.id, layer.visible !== false])));
    setActiveId(null);
    setActiveDbKey(null);
    setDirty(true);
  }

  function rotate(delta: number) {
    setCamera((current) => ({ ...current, yaw: current.yaw + delta }));
  }

  function zoom(delta: number) {
    setCamera((current) => ({ ...current, zoom: Math.max(0.6, Math.min(2.4, current.zoom + delta)) }));
  }

  function startCanvasDrag(event: React.PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    window.getSelection?.()?.removeAllRanges();
    viewMoved.current = false;
    setViewDrag({ x: event.clientX, y: event.clientY });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function moveCanvas(event: React.PointerEvent<SVGSVGElement>) {
    if (draggingId && configOpen && canEdit) {
      setPointPosition(draggingId, inverseScenePoint(event, camera));
      return;
    }
    if (!viewDrag) return;
    const dx = event.clientX - viewDrag.x;
    const dy = event.clientY - viewDrag.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) viewMoved.current = true;
    setCamera((current) => ({ ...current, yaw: current.yaw + dx * 0.008, pitch: Math.max(0.22, Math.min(0.9, current.pitch - dy * 0.004)) }));
    setViewDrag({ x: event.clientX, y: event.clientY });
  }

  function endCanvasDrag(event: React.PointerEvent<SVGSVGElement>) {
    setDraggingId(null);
    setViewDrag(null);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  }

  function clickCanvas(event: React.MouseEvent<SVGSVGElement>) {
    if (viewMoved.current) {
      viewMoved.current = false;
      return;
    }
    if (!configOpen || !canEdit) return;
    const position = inverseScenePoint(event, camera);
    if (activeId) setPointPosition(activeId, position);
    else if (activeDbKey) addSelectedPoint(position);
  }

  function markerItem(entry: TwinPoint): DatabasePoint {
    return { key: pointKey(entry.measurement_key, entry.point), measurement_key: entry.measurement_key, point: entry.point, label: entry.measurement_key };
  }

  function markerPointerDown(event: React.PointerEvent<SVGGElement>, entry: TwinPoint) {
    event.stopPropagation();
    event.preventDefault();
    window.getSelection?.()?.removeAllRanges();
    if (configOpen && canEdit) {
      const item = markerItem(entry);
      selectDatabasePoint(item);
      setDraggingId(entry.id);
    }
  }

  function markerClick(event: React.MouseEvent<SVGGElement>, entry: TwinPoint) {
    event.stopPropagation();
    const item = markerItem(entry);
    if (configOpen && canEdit) {
      selectDatabasePoint(item);
      return;
    }
    if (pointChart?.measurement_key === item.measurement_key && pointChart.settings.points[0] === item.point) {
      setPointChart(null);
      setChartError("");
      return;
    }
    void showPointChart(item);
  }

  return (
    <section className="panel digital-twin-panel">
      <div className="panel-heading">
        <div>
          <h2><Box size={20} />数字孪生 3D 沙盘</h2>
          <p>浏览模式拖动旋转视角，点击点位查看数据图表；展开点位配置后可调整位置。</p>
        </div>
        <div className="toolbar-group">
          {canEdit && <>
            <Button onClick={() => fileRef.current?.click()}><Upload size={16} />导入场景 JSON</Button>
            <input ref={fileRef} hidden type="file" accept=".json,application/json" aria-label="导入数字孪生场景" onChange={(event) => { const file = event.target.files?.[0]; if (file) action.run(() => importScene(file), "数字孪生场景已导入"); event.target.value = ""; }} />
            <Button onClick={() => dwgFileRef.current?.click()}><FileUp size={16} />上传 DWG 自动生成</Button>
            <input ref={dwgFileRef} hidden type="file" accept=".dwg,application/acad" aria-label="上传 DWG 自动生成" onChange={(event) => { const file = event.target.files?.[0]; if (file) action.run(() => previewDwg(file), "DWG 已解析为场景，请核对后保存"); event.target.value = ""; }} />
          </>}
          {scene && canEdit && <Button kind="primary" disabled={!dirty} busy={action.busy} onClick={() => action.run(async () => { const result = await api<{ scene: TwinScene; revision: number }>(base + "/twin/scene", json({ revision, scene }, "PUT")); setScene(cleanScene(result.scene)); setRevision(result.revision); setDirty(false); }, "数字孪生场景已保存")}><Save size={16} />保存沙盘</Button>}
        </div>
      </div>
      <Notice>{action.error || chartError}</Notice>
      <Notice success>{action.success}</Notice>
      {!scene ? <Empty title="尚未导入数字孪生场景">{canEdit ? "请导入由 DWG 解析器生成的场景 JSON，然后从数据库选择测点。" : "当前工程还没有数字孪生场景。"}</Empty> : <>
        <div className={`digital-twin-workspace ${configOpen ? "" : "digital-twin-workspace--full"}`}>
          <div className="digital-twin-canvas-wrap">
            <div className="digital-twin-canvas-toolbar">
              <span className="muted"><MousePointer2 size={14} />{configOpen ? (activeId ? `配置模式：已选择 ${selected?.point || "测点"}` : "配置模式：选择点位后拖动或点击画布") : "浏览模式：按住鼠标拖动视角，点击点位查看图表"}</span>
              <span className="muted">{scene.objects.length} 个结构图形 · {placed.length} 个数据库测点</span>
              <span className="digital-twin-view-controls">
                {canEdit && <button type="button" className="digital-twin-config-inline" aria-label={configOpen ? "收起点位配置" : "展开点位配置"} aria-expanded={configOpen} onClick={() => setConfigOpen((current) => !current)}><Settings2 size={14} />{configOpen ? "收起配置" : "点位配置"}</button>}
                <button type="button" aria-label="向左旋转" onClick={() => rotate(-0.18)}><RotateCcw size={14} /></button>
                <button type="button" aria-label="向右旋转" onClick={() => rotate(0.18)}><RotateCw size={14} /></button>
                <button type="button" aria-label="放大沙盘" onClick={() => zoom(0.15)}><ZoomIn size={14} /></button>
                <button type="button" aria-label="缩小沙盘" onClick={() => zoom(-0.15)}><ZoomOut size={14} /></button>
                <button type="button" aria-label="重置三维视角" onClick={() => setCamera({ yaw: -0.34, pitch: 0.46, zoom: 1 })}>复位</button>
              </span>
            </div>
            {chartLoading && <p className="muted digital-twin-chart-loading">正在读取点位图表…</p>}
            <svg className="digital-twin-canvas digital-twin-canvas-3d" viewBox="0 0 100 80" preserveAspectRatio="none" role="application" aria-label="数字孪生三维沙盘" onPointerDown={startCanvasDrag} onPointerMove={moveCanvas} onPointerUp={endCanvasDrag} onPointerCancel={endCanvasDrag} onDragStart={(event) => event.preventDefault()} onClick={clickCanvas}>
              <title>基坑结构的可旋转三维等轴沙盘</title>
              <rect width="100" height="80" fill="#f5f9fa" />
              <polygon points={pointString([[0.03, 0.95], [0.97, 0.95], [0.97, 0.05], [0.03, 0.05]].map((point) => projectPoint(point as [number, number], 0, camera)))} fill="#e7eff0" stroke="#c5d7da" strokeWidth="0.22" />
              {Array.from({ length: 9 }, (_, index) => { const offset = (index + 1) / 10; const a = projectPoint([offset, 0], 0, camera), b = projectPoint([offset, 1], 0, camera), c = projectPoint([0, offset], 0, camera), d = projectPoint([1, offset], 0, camera); return <g key={index} opacity="0.55"><line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#c9dadd" strokeWidth="0.12" /><line x1={c[0]} y1={c[1]} x2={d[0]} y2={d[1]} stroke="#c9dadd" strokeWidth="0.12" /></g>; })}
              {scene.objects.filter((object) => visibleLayers[object.layer_id || ""] !== false).map((object) => { const layerIndex = scene.layers.findIndex((layer) => layer.id === object.layer_id); const layer = scene.layers[layerIndex]; return <g key={object.id}><Geometry3D geometry={object.geometry} stroke={PALETTE[layerIndex % PALETTE.length] || "#587786"} height={Number(object.height) || layerHeight(layer?.name || "结构")} camera={camera} /></g>; })}
              {placed.filter((entry) => entry.position && entry.visible !== false).map((entry) => { const position = entry.position!; const basePoint = projectPoint(position, 0, camera); const topPoint = projectPoint(position, Number(entry.elevation) || 0.18, camera); return <g key={entry.id} className="digital-twin-sensor" onPointerDown={(event) => markerPointerDown(event, entry)}><line x1={basePoint[0]} y1={basePoint[1]} x2={topPoint[0]} y2={topPoint[1]} stroke="#c26b19" strokeWidth="0.38" /><circle cx={topPoint[0]} cy={topPoint[1]} r="1.05" fill="#c26b19" stroke={activeId === entry.id ? "#102a43" : "white"} strokeWidth="0.22" onClick={(event) => markerClick(event, entry)} /><text x={basePoint[0] + 1.1} y={basePoint[1] - 0.4} fontSize="2.2" fill="#234" paintOrder="stroke" stroke="white" strokeWidth="0.65" pointerEvents="none">{entry.point}</text></g>; })}
            </svg>
          </div>
          {configOpen && <aside className="digital-twin-inspector">
            <div className="digital-twin-config-heading"><h3>点位配置</h3><span className="count">{databasePoints.length}</span></div>
            {configOpen && <div className="digital-twin-config-body">
              <h3>图层</h3>
              <div className="digital-twin-layers">{scene.layers.map((layer) => <label key={layer.id}><input type="checkbox" checked={visibleLayers[layer.id] !== false} onChange={(event) => setVisibleLayers((current) => ({ ...current, [layer.id]: event.target.checked }))} />{visibleLayers[layer.id] !== false ? <Eye size={14} /> : <EyeOff size={14} />}{layer.name}</label>)}</div>
              <h3>数据库测点 <span className="count">{databasePoints.length}</span></h3>
              <p className="muted">配置模式下点击或拖动测点调整位置。</p>
              {databasePoints.length ? <><label className="field digital-twin-point-picker"><span>测项</span><select aria-label="数据库测项" value={selectedMeasurement} onChange={(event) => { const item = databasePoints.find((entry) => entry.measurement_key === event.target.value); if (item) selectDatabasePoint(item); }}>{Array.from(new Map(databasePoints.map((item) => [item.measurement_key, item])).values()).map((item) => <option key={item.measurement_key} value={item.measurement_key}>{item.label} · {item.measurement_key}</option>)}</select></label><label className="field digital-twin-point-picker"><span>点号</span><select aria-label="数据库点号" value={selectedPoint} onChange={(event) => { const item = databasePoints.find((entry) => entry.measurement_key === selectedMeasurement && entry.point === event.target.value); if (item) selectDatabasePoint(item); }}>{databasePoints.filter((item) => item.measurement_key === selectedMeasurement).map((item) => <option key={item.key} value={item.point}>{item.point}</option>)}</select></label><Button kind="primary full" disabled={!selectedDb || placedKeys.has(selectedDb.key)} onClick={() => addSelectedPoint()}><Plus size={15} />{selectedDb && placedKeys.has(selectedDb.key) ? "已在沙盘" : "添加到沙盘"}</Button></> : <span className="muted">暂无数据库测点</span>}
              <div className="digital-twin-unplaced">{available.length ? available.map((item) => <button key={item.key} className={activeDbKey === item.key ? "active" : ""} onClick={() => selectDatabasePoint(item)}>选择 {item.point}<small>{item.label} · {item.measurement_key}</small></button>) : databasePoints.length ? <span className="muted">所有数据库测点均已放入沙盘</span> : null}</div>
              {selected && <div className="digital-twin-selection"><strong>{selected.point}</strong><span>{selected.measurement_key}</span><span>已放置到三维场景</span><Button onClick={removeSelectedPoint}><Trash2 size={14} />移出沙盘</Button></div>}
            </div>}
          </aside>}
        </div>
        {pointChart && <Modal title={`点位数据图表 · ${pointChart.settings.points[0]}`} onClose={() => setPointChart(null)}><div className="digital-twin-chart-popup"><Suspense fallback={<p className="muted">正在绘制点位图表…</p>}><ReportChart data={pointChart} compact /></Suspense></div></Modal>}
      </>}
    </section>
  );
}
