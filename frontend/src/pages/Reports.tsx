import { useState } from "react";
import { FileChartColumn, Download, Eye } from "lucide-react";
import { api, json, download, type DataSet, type Project } from "../api";
import { Button, Empty, Notice, useAction } from "../components/Common";
import { ScopeFields, initialScope } from "../components/ScopeFields";
import { AnalysisTable } from "./Analysis";
export function Reports({
  project,
  data,
}: {
  project: Project;
  data: DataSet;
}) {
  const [scope, setScope] = useState(initialScope(data)),
    [report, setReport] = useState<any>(null),
    action = useAction();
  return (
    <div className="analysis-layout">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              <FileChartColumn size={20} />
              监测日报
            </h2>
            <p>先预览数据与待复核事项，再导出 Excel 报告。</p>
          </div>
        </div>
        <Notice>{action.error}</Notice>
        {report ? (
          <>
            <div className="report-heading">
              <span className="eyebrow">MONITORING REPORT</span>
              <h2>{report.project_name}</h2>
              <p>
                {report.analysis.start_date} — {report.analysis.end_date}
              </p>
            </div>
            <pre className="report-summary">{report.summary_text}</pre>
            <Notice>{report.notice}</Notice>
            <AnalysisTable result={report.analysis} />
          </>
        ) : (
          <Empty title="生成本工程的监测报告">
            选择测项和日期范围，点击“预览报告”。报告包括统计摘要、分析明细和待复核事项。
          </Empty>
        )}
      </section>
      <aside className="panel scope-panel">
        <h2>报告范围</h2>
        <ScopeFields data={data} scope={scope} setScope={setScope} />
        <Button
          kind="primary full"
          busy={action.busy}
          disabled={!data.catalog.length}
          onClick={() =>
            action.run(async () =>
              setReport(
                await api(
                  "/projects/" + project.id + "/reports/preview",
                  json(scope),
                ),
              ),
            )
          }
        >
          <Eye size={16} />
          预览报告
        </Button>
        <Button
          kind="full"
          disabled={!report}
          busy={action.busy}
          onClick={() =>
            action.run(async () =>
              download(
                "/projects/" + project.id + "/reports/download",
                project.name + "-监测日报.xlsx",
                report.scope,
              ),
            )
          }
        >
          <Download size={16} />
          导出预览范围 Excel
        </Button>
        <p className="muted scope-note">
          网页版提供标准报告。桌面版复杂模板排版可继续在原软件中完成。
        </p>
      </aside>
    </div>
  );
}
