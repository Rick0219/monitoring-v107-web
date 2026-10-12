import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  useParams,
  useNavigate,
  useBlocker,
} from "@tanstack/react-router";
import {
  ArrowLeft,
  Upload,
  Download,
  Settings2,
  Database,
  Table2,
  BarChart3,
  Sparkles,
  FileChartColumn,
  Users,
} from "lucide-react";
import {
  api,
  json,
  download,
  type Project,
  type DataSet,
  type User,
} from "../api";
import { ProjectMembers } from "../components/ProjectMembers";
import { DeleteProject } from "../components/DeleteProject";
import { Button, Field, Modal, Notice, useAction } from "../components/Common";
import { DataEntry } from "./DataEntry";
import { Analysis } from "./Analysis";
import { Reports } from "./Reports";
import { ProjectDatabase } from "./ProjectDatabase";
export function ProjectWorkspace() {
  const { projectId } = useParams({ strict: false }) as { projectId: string };
  return <Workspace key={projectId} id={projectId} />;
}
function Workspace({ id }: { id: string }) {
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => api<Project>("/projects/" + id),
    refetchOnWindowFocus: "always",
  });
  const data = useQuery({
    queryKey: ["project-data", id],
    queryFn: () => api<DataSet>("/projects/" + id + "/catalog"),
    enabled: !!project.data?.permissions.length,
  });
  const [tab, setTab] = useState("data"),
    [dirty, setDirty] = useState(false),
    [settings, setSettings] = useState(false),
    [edit, setEdit] = useState({ name: "", location: "", description: "" });
  const [entryVersion, setEntryVersion] = useState(0);
  const [membersOpen, setMembersOpen] = useState(false);
  const action = useAction(),
    cache = useQueryClient(),
    navigate = useNavigate(),
    fileRef = useRef<HTMLInputElement>(null);
  useBlocker({
    shouldBlockFn: () =>
      dirty && !confirm("数据尚未保存，离开将放弃修改。继续？"),
    enableBeforeUnload: dirty,
  });
  if (project.error || data.error)
    return <Notice>{project.error?.message || data.error?.message}</Notice>;
  if (!project.data || (project.data.permissions.length > 0 && !data.data))
    return <div className="loading">正在读取工程数据…</div>;
  const p = project.data;
  const user = cache.getQueryData<User>(["me"]);
  const permits = (permission: string) => p.permissions.includes(permission);
  const canEdit = permits("data_entry");
  const canManage =
    !!user && (user.is_superuser || (user.id === p.owner_id && canEdit));
  const tabs = [
    {
      key: "data",
      permission: "data_entry",
      label: "数据录入",
      Icon: Database,
    },
    {
      key: "database_data",
      permission: "database_data",
      label: "数据库数据",
      Icon: Table2,
    },
    {
      key: "database_charts",
      permission: "database_charts",
      label: "数据库图表",
      Icon: BarChart3,
    },
    {
      key: "analysis",
      permission: "analysis",
      label: "智能分析",
      Icon: Sparkles,
    },
    {
      key: "reports",
      permission: "reports",
      label: "报告生成",
      Icon: FileChartColumn,
    },
  ].filter((item) => permits(item.permission));
  const activeTab = tabs.some((item) => item.key === tab) ? tab : tabs[0]?.key;
  const refresh = async () => {
    await cache.invalidateQueries({ queryKey: ["project", id] });
    await cache.invalidateQueries({ queryKey: ["project-data", id] });
    await cache.invalidateQueries({ queryKey: ["projects"] });
  };
  return (
    <>
      <Link to="/" className="back-link">
        <ArrowLeft size={16} />
        返回我的项目
      </Link>
      <section className="page-heading workspace-heading">
        <div>
          <h1>{p.name}</h1>
          <p>
            {p.location || "未填写位置"}
            <span className="dot">·</span>
            {p.owner_name}
            <span className="dot">·</span>
            {p.measurement_count} 个测项 / {p.row_count} 条数据
          </p>
        </div>
        <div className="toolbar-group">
          {!!user && (user.is_superuser || user.id === p.owner_id) && (
            <DeleteProject
              project={p}
              onDeleted={() => {
                setDirty(false);
                void navigate({ to: "/" });
              }}
            />
          )}
          {canManage && (
            <Button onClick={() => setMembersOpen(true)}>
              <Users size={16} />
              工程成员
            </Button>
          )}
          {canEdit && (
            <Button busy={action.busy} onClick={() => fileRef.current?.click()}>
              <Upload size={16} />
              导入工程
            </Button>
          )}
          <input
            type="file"
            accept=".proj"
            ref={fileRef}
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              if (!confirm("导入会替换当前工程的原始数据和计算参数。继续？")) {
                e.target.value = "";
                return;
              }
              action.run(async () => {
                const form = new FormData();
                form.append("file", file);
                await api(
                  "/projects/" + id + "/import?revision=" + data.data!.revision,
                  { method: "POST", body: form },
                );
                setDirty(false);
                await refresh();
                setEntryVersion((v) => v + 1);
              }, "桌面工程数据已导入");
              e.target.value = "";
            }}
          />
          {canEdit && (
            <Button
              busy={action.busy}
              onClick={() =>
                action.run(async () =>
                  download("/projects/" + id + "/export", p.name + ".proj"),
                )
              }
            >
              <Download size={16} />
              导出工程
            </Button>
          )}
          {canEdit && (
            <Button
              onClick={() => {
                setEdit({
                  name: p.name,
                  location: p.location,
                  description: p.description,
                });
                setSettings(true);
              }}
              aria-label="工程设置"
            >
              <Settings2 size={16} />
            </Button>
          )}
        </div>
      </section>
      <Notice>{action.error}</Notice>
      <Notice success>{action.success}</Notice>
      <div className="workspace-tabs" role="tablist" aria-label="工程功能">
        {tabs.map(({ key, label, Icon }) => (
          <button
            key={key}
            role="tab"
            aria-selected={activeTab === key}
            className={activeTab === key ? "active" : ""}
            onClick={() => {
              if (dirty && !confirm("数据尚未保存，切换将放弃修改。继续？"))
                return;
              setDirty(false);
              setTab(key);
            }}
          >
            <Icon size={18} />
            {label}
          </button>
        ))}
      </div>
      {activeTab === "data" && data.data ? (
        <EntryLoader
          key={entryVersion}
          project={p}
          data={data.data}
          onDirty={setDirty}
        />
      ) : (activeTab === "database_data" || activeTab === "database_charts") &&
        data.data ? (
        <ProjectDatabase
          view={activeTab === "database_data" ? "data" : "charts"}
          project={p}
          data={data.data}
          onDirty={setDirty}
        />
      ) : activeTab === "analysis" && data.data ? (
        <Analysis project={p} data={data.data} />
      ) : activeTab === "reports" && data.data ? (
        <Reports project={p} data={data.data} />
      ) : (
        <Notice>当前账号尚未获授功能权限，请联系管理员。</Notice>
      )}
      {membersOpen && canManage && (
        <ProjectMembers projectId={id} onClose={() => setMembersOpen(false)} />
      )}
      {settings && canEdit && (
        <Modal title="工程设置" onClose={() => setSettings(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.run(async () => {
                await api(
                  "/projects/" + id,
                  json({ ...edit, revision: p.revision }, "PATCH"),
                );
                await refresh();
                setSettings(false);
              });
            }}
          >
            <Field label="工程名称">
              <input
                required
                maxLength={120}
                value={edit.name}
                onChange={(e) => setEdit({ ...edit, name: e.target.value })}
              />
            </Field>
            <Field label="工程位置">
              <input
                maxLength={200}
                value={edit.location}
                onChange={(e) => setEdit({ ...edit, location: e.target.value })}
              />
            </Field>
            <Field label="工程说明">
              <textarea
                maxLength={2000}
                value={edit.description}
                onChange={(e) =>
                  setEdit({ ...edit, description: e.target.value })
                }
              />
            </Field>
            <Notice>{action.error}</Notice>
            <div className="modal-actions">
              <Button kind="primary" busy={action.busy}>
                保存设置
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function EntryLoader({
  project,
  data,
  onDirty,
}: {
  project: Project;
  data: DataSet;
  onDirty: (dirty: boolean) => void;
}) {
  return <DataEntry project={project} data={data} onDirty={onDirty} />;
}
