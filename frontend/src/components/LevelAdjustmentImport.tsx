import { useMemo, useState } from "react";
import { CheckCircle2, FileUp, UploadCloud } from "lucide-react";
import { api, json, type DataSet, type Project } from "../api";
import { Button, Field, Form, Modal, Notice, useAction } from "./Common";

const EXTENSIONS = ["DAT", "BM1", "hdf", "in1", "gco", "ou1", "our"] as const;
type Extension = (typeof EXTENSIONS)[number];
type WeightMode = "distance" | "station";

type Preview = {
  import_id: string;
  mode: "adjusted" | "raw";
  message: string;
  project_revision: number;
  generated_files: { name: string; bytes: number; url: string }[];
  files: { name: string; bytes: number; sha256: string }[];
  result: {
    points: Record<string, { point: string; elevation: number; fixed: boolean }>;
    observations: { from_point: string; to_point: string; observed_delta_h: number; adjusted_delta_h: number }[];
    known_points: Record<string, number>;
    route_start: string;
    route_end: string;
    total_distance_km: number;
  };
  quality: { status: string; can_apply: boolean; closure_error_mm: number | null; limit_mm_per_km: number | null; warnings: string[] };
  cross_checks: { source: string; status: "matched" | "mismatch" | "missing"; detail: string }[];
  mapping_candidates: Record<string, string[]>;
};

export function LevelAdjustmentImport({
  project,
  data,
  onApplied,
}: {
  project: Project;
  data: DataSet;
  onApplied: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"files" | "settings" | "mapping">("files");
  const [files, setFiles] = useState<Partial<Record<Extension, File>>>({});
  const [weightMode, setWeightMode] = useState<WeightMode>("distance");
  const [observedDate, setObservedDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [preview, setPreview] = useState<Preview | null>(null);
  const [measurementKey, setMeasurementKey] = useState("");
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [allowOutOfTolerance, setAllowOutOfTolerance] = useState(false);
  const action = useAction();

  const levelMeasurements = useMemo(
    () => data.catalog.filter((item) => item.key.startsWith("level:")),
    [data.catalog],
  );
  const targetPoints = useMemo(() => {
    const selected = levelMeasurements.find((item) => item.key === measurementKey);
    return selected?.points || [];
  }, [levelMeasurements, measurementKey]);
  const hasObservationFile = Boolean(files.DAT);

  function reset() {
    setStep("files");
    setFiles({});
    setWeightMode("distance");
    setObservedDate(new Date().toISOString().slice(0, 10));
    setPreview(null);
    setMeasurementKey(levelMeasurements[0]?.key || "level:建筑物位移");
    setMappings({});
    setAllowOutOfTolerance(false);
    action.clearStatus();
  }

  function close() {
    if (!action.busy) {
      setOpen(false);
      reset();
    }
  }

  async function previewFiles() {
    if (!hasObservationFile) {
      action.setError("请先选择 DAT 观测文件");
      return;
    }
    await action.run(async () => {
      const form = new FormData();
      Object.values(files).forEach((file) => form.append("files", file));
      form.append("weight_mode", weightMode);
      form.append("observed_date", observedDate);
      const response = await api<Preview>(
        `/projects/${project.id}/level-adjustment/preview`,
        { method: "POST", body: form },
      );
      setPreview(response);
      setMeasurementKey(levelMeasurements[0]?.key || "level:建筑物位移");
      setMappings(
        Object.fromEntries(
          Object.values(response.result.points).map((point) => [
            point.point,
            response.mapping_candidates[point.point]?.[0] || point.point,
          ]),
        ),
      );
      setStep("mapping");
    });
  }

  function nextFromFiles() {
    if (!hasObservationFile) {
      action.setError("请先选择 DAT 观测文件");
      return;
    }
    if (files.BM1) {
      setStep("settings");
      return;
    }
    void previewFiles();
  }

  async function apply() {
    if (!preview) return;
    const selected = Object.entries(mappings).filter(([, value]) => value);
    if (!selected.length) {
      action.setError("请至少选择一个数据库点号");
      return;
    }
    await action.run(async () => {
      await api(`/projects/${project.id}/level-adjustment/apply`, {
        ...json(
          {
            revision: preview.project_revision,
            import_id: preview.import_id,
            measurement_key: measurementKey,
            observed_date: observedDate,
            weight_mode: weightMode,
            allow_out_of_tolerance: allowOutOfTolerance,
            mappings: selected.map(([adjusted_point, database_point]) => ({
              adjusted_point,
              database_point,
              enabled: true,
            })),
          },
          "PUT",
        ),
      });
      await onApplied();
      setOpen(false);
      reset();
    }, "平差结果已写入今日测值");
  }

  return (
    <>
      <Button kind="secondary" onClick={() => setOpen(true)}>
        <FileUp size={16} />
        原始数据导入
      </Button>
      {open && (
        <Modal title="原始数据导入" onClose={close}>
          <div className="level-adjustment-wizard">
            <div className="level-adjustment-steps" aria-label="导入步骤">
              <span className={step === "files" ? "active" : "done"}>1. 选择原始文件</span>
              <span className={step === "settings" ? "active" : preview ? "done" : ""}>2. 平差设置</span>
              <span className={step === "mapping" ? "active" : ""}>3. 点号映射与写入</span>
            </div>
            <Notice>{action.error}</Notice>
            <Notice success>{action.success}</Notice>

            {step === "files" && (
              <Form onSubmit={() => setStep("settings")}>
                <h3>选择原始文件</h3>
                <p className="muted">DAT 为必选观测文件；上传 BM1 后进行水准平差并生成派生文件，只有 DAT 时直接提取观测高程并进行点号映射。</p>
                <div className="level-adjustment-file-grid">
                  {EXTENSIONS.map((extension) => (
                    <label className="level-adjustment-file" key={extension}>
                      <strong>.{extension}</strong>
                      <span>{files[extension]?.name || "选择文件"}</span>
                      <input
                        type="file"
                        accept={`.${extension}`}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) setFiles((current) => ({ ...current, [extension]: file }));
                        }}
                      />
                    </label>
                  ))}
                </div>
                <div className="modal-actions">
                  <Button type="button" onClick={close}>取消</Button>
                  <Button type="button" kind="primary" disabled={!hasObservationFile} busy={action.busy} onClick={nextFromFiles}>下一步</Button>
                </div>
              </Form>
            )}

            {step === "settings" && (
              <Form onSubmit={previewFiles}>
                <h3>平差设置</h3>
                <div className="level-adjustment-settings">
                  <Field label="观测日期">
                    <input type="date" value={observedDate} onChange={(event) => setObservedDate(event.target.value)} required />
                  </Field>
                  <Field label="定权方式">
                    <select value={weightMode} onChange={(event) => setWeightMode(event.target.value as WeightMode)}>
                      <option value="distance">按距离定权</option>
                      <option value="station">按测站定权</option>
                    </select>
                  </Field>
                </div>
                <p className="muted">系统会先计算闭合差和限差，再展示平差后的高程。</p>
                <div className="modal-actions">
                  <Button type="button" onClick={() => setStep("files")}>上一步</Button>
                  <Button type="submit" kind="primary" busy={action.busy}>
                    <UploadCloud size={16} /> 预览平差结果
                  </Button>
                </div>
              </Form>
            )}

            {step === "mapping" && preview && (
              <div>
                <h3>点号映射与写入</h3>
                <Notice success>{preview.message}</Notice>
                <p className="muted">将{preview.mode === "adjusted" ? "平差点号" : "观测点号"}对应到数据库点号，未选中的点不会写入。</p>
                <div className="level-adjustment-summary">
                  <span>已知点：{Object.keys(preview.result.known_points).join("、")}</span>
                  <span>路线：{preview.result.route_start} → {preview.result.route_end}</span>
                  <span>测段：{preview.result.observations.length} 段</span>
                  <span>总距离：{preview.result.total_distance_km.toFixed(4)} km</span>
                  <span>闭合差：{preview.quality.closure_error_mm == null ? "未计算（未平差）" : `${preview.quality.closure_error_mm.toFixed(4)} mm`}</span>
                  <span>限差：{preview.quality.limit_mm_per_km == null ? "未提供" : `${preview.quality.limit_mm_per_km} mm/km`}</span>
                  <span>{preview.mode === "raw" ? "未进行平差" : preview.quality.status === "passed" ? "质量检查通过" : "质量检查需要处理"}</span>
                </div>
                {preview.generated_files.length > 0 && <div className="level-adjustment-generated"><strong>已生成派生文件：</strong>{preview.generated_files.map((file) => <a key={file.name} href={file.url} download>{file.name}</a>)}</div>}
                <Notice>{preview.cross_checks.filter((item) => item.status !== "matched").map((item) => `${item.source}: ${item.detail}`).join("；")}</Notice>
                <Field label="写入测项">
                  <select value={measurementKey} onChange={(event) => setMeasurementKey(event.target.value)}>
                    {levelMeasurements.length ? levelMeasurements.map((item) => <option key={item.key} value={item.key}>{item.label || item.key}</option>) : <option value="level:建筑物位移">建筑物位移</option>}
                  </select>
                </Field>
                <div className="level-adjustment-table-wrap">
                  <table className="level-adjustment-table">
                    <thead><tr><th>平差点号</th><th>平差高程（m）</th><th>数据库点号</th></tr></thead>
                    <tbody>
                      {Object.values(preview.result.points).map((point) => {
                        const candidates = Array.from(new Set([...(preview.mapping_candidates[point.point] || []), ...targetPoints]));
                        return <tr key={point.point}><td>{point.point}</td><td>{point.elevation.toFixed(4)}</td><td><select aria-label={`映射 ${point.point}`} value={mappings[point.point] || ""} onChange={(event) => setMappings((current) => ({ ...current, [point.point]: event.target.value }))}><option value="">跳过</option>{candidates.map((candidate) => <option key={candidate} value={candidate}>{candidate}</option>)}</select></td></tr>;
                      })}
                    </tbody>
                  </table>
                </div>
                {preview.mode === "adjusted" && !preview.quality.can_apply && <label className="level-adjustment-warning"><input type="checkbox" checked={allowOutOfTolerance} onChange={(event) => setAllowOutOfTolerance(event.target.checked)} /> 仍然写入超限结果</label>}
                <div className="modal-actions">
                  <Button type="button" onClick={() => setStep("settings")}>重新计算</Button>
                  <Button type="button" kind="primary" busy={action.busy} disabled={preview.mode === "adjusted" && !preview.quality.can_apply && !allowOutOfTolerance} onClick={apply}><CheckCircle2 size={16} /> 写入今日测值</Button>
                </div>
              </div>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
