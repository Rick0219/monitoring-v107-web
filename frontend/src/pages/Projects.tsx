import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, Navigate } from "@tanstack/react-router";
import {
  Plus,
  Search,
  ArrowUpRight,
  MapPin,
  FolderOpen,
  Database,
  Layers,
} from "lucide-react";
import { api, json, type Project, type User } from "../api";
import { DeleteProject } from "../components/DeleteProject";
import {
  Button,
  Empty,
  Field,
  Modal,
  Notice,
  useAction,
} from "../components/Common";
export function Projects({ all = false }: { all?: boolean }) {
  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/users/me"),
    refetchOnWindowFocus: "always",
  });
  const query = useQuery({
    queryKey: ["projects", all],
    queryFn: () =>
      api<{ data: Project[]; count: number }>(
        "/projects" + (all ? "/all" : ""),
      ),
    enabled: !all || !!user?.is_superuser,
  });
  const [search, setSearch] = useState(""),
    [show, setShow] = useState(false),
    [name, setName] = useState(""),
    [location, setLocation] = useState(""),
    [description, setDescription] = useState("");
  const action = useAction(),
    cache = useQueryClient(),
    navigate = useNavigate();
  if (all && user && !user.is_superuser) return <Navigate to="/" />;
  const canCreate = !!user?.permissions.includes("data_entry");
  const projects = query.data?.data || [],
    filtered = projects.filter((p) =>
      (p.name + p.location + p.owner_name)
        .toLowerCase()
        .includes(search.toLowerCase()),
    );
  return (
    <>
      <section className="page-heading">
        <div>
          <span className="eyebrow">PROJECT WORKSPACE</span>
          <h1>{all ? "全部项目" : "我的项目"}</h1>
          <p>
            {all
              ? "查看各账号创建的工程，进入对应工作空间。"
              : "查看我创建和参与的工程，共同整理监测数据、完成分析与报告。"}
          </p>
        </div>
        {canCreate && (
          <Button kind="primary" onClick={() => setShow(true)}>
            <Plus size={18} />
            新建工程
          </Button>
        )}
      </section>
      <div className="metrics">
        <div>
          <span className="metric-icon">
            <FolderOpen />
          </span>
          <section>
            <small>{all ? "工程总数" : "我的工程"}</small>
            <strong>
              {projects.length}
              <em>个</em>
            </strong>
          </section>
        </div>
        <div>
          <span className="metric-icon green">
            <Layers />
          </span>
          <section>
            <small>监测测项</small>
            <strong>
              {projects.reduce((n, p) => n + p.measurement_count, 0)}
              <em>项</em>
            </strong>
          </section>
        </div>
        <div>
          <span className="metric-icon orange">
            <Database />
          </span>
          <section>
            <small>原始数据记录</small>
            <strong>
              {projects.reduce((n, p) => n + p.row_count, 0).toLocaleString()}
              <em>条</em>
            </strong>
          </section>
        </div>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              工程列表 <span className="count">{filtered.length}</span>
            </h2>
            <p>选择工程，继续你的工作</p>
          </div>
          <label className="search">
            <Search size={17} />
            <input
              aria-label="搜索工程"
              placeholder="搜索工程名称、位置或负责人"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
        <Notice>{query.error?.message}</Notice>
        {query.isPending ? (
          <div className="loading">正在加载工程…</div>
        ) : !filtered.length ? (
          <Empty
            title={
              search
                ? "没有匹配的工程"
                : canCreate
                  ? "开始你的第一个工程"
                  : "暂无参与的工程"
            }
          >
            {search
              ? "请尝试其他关键词。"
              : canCreate
                ? "点击“新建工程”，填写名称后即可录入监测数据，也可以导入桌面版工程文件。"
                : "请联系管理员将你的账号加入工程并设置功能权限。"}
          </Empty>
        ) : (
          <div className="project-grid">
            {filtered.map((p) => (
              <div key={p.id} className="project-list-item">
                <Link
                  to="/projects/$projectId"
                  params={{ projectId: p.id }}
                  key={p.id}
                  className="project-card"
                >
                  <div className="project-card-top">
                    <span className="project-symbol">
                      <FolderOpen size={23} />
                    </span>
                    <span className="pill subtle">
                      {p.measurement_count ? "已录入数据" : "待录入"}
                    </span>
                  </div>
                  <h3>
                    {p.name}
                    <ArrowUpRight size={19} />
                  </h3>
                  <p className="project-description">
                    {p.description || "暂无工程说明"}
                  </p>
                  <div className="location">
                    <MapPin size={14} />
                    {p.location || "未填写位置"}
                  </div>
                  <div className="project-card-stats">
                    <span>
                      <strong>{p.measurement_count}</strong> 测项
                    </span>
                    <span>
                      <strong>{p.row_count}</strong> 条数据
                    </span>
                  </div>
                  <footer>
                    <span>
                      {all
                        ? p.owner_name
                        : p.owner_id === user?.id
                          ? "我创建的工程"
                          : "参与的工程 · " + p.owner_name}
                    </span>
                    <time>
                      {new Date(
                        /(Z|[+-]\d{2}:\d{2})$/i.test(p.updated_at)
                          ? p.updated_at
                          : p.updated_at + "Z",
                      ).toLocaleDateString("zh-CN")}
                    </time>
                  </footer>
                </Link>
                {(user?.is_superuser || p.owner_id === user?.id) && (
                  <div className="project-delete-action">
                    <DeleteProject project={p} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      {show && canCreate && (
        <Modal title="新建工程" onClose={() => setShow(false)}>
          <p className="muted">工程将自动归属于当前登录账号。</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.run(async () => {
                const p = await api<Project>(
                  "/projects",
                  json({ name, location, description }),
                );
                await cache.invalidateQueries({ queryKey: ["projects"] });
                await navigate({
                  to: "/projects/$projectId",
                  params: { projectId: p.id },
                });
              });
            }}
          >
            <Field label="工程名称">
              <input
                autoFocus
                required
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：绿岛湖北站附属工程"
              />
            </Field>
            <Field label="工程位置">
              <input
                maxLength={200}
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="城市、区段或施工位置"
              />
            </Field>
            <Field label="工程说明">
              <textarea
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="填写监测范围或工程概况"
              />
            </Field>
            <Notice>{action.error}</Notice>
            <div className="modal-actions">
              <Button type="button" onClick={() => setShow(false)}>
                取消
              </Button>
              <Button kind="primary" busy={action.busy}>
                创建并进入工程
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
