import { useParams, useSearch, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Project, type User } from "../api";
import { Button, Notice } from "../components/Common";
import { ChartCard } from "./ProjectDatabase";
import { rememberLoginDestination } from "../authNavigation";

export function ChartPage() {
  const { projectId } = useParams({ strict: false }) as { projectId: string };
  const { measurement } = useSearch({ from: "/workspace/charts/$projectId" });
  const cache = useQueryClient();
  const user = cache.getQueryData<User>(["me"]);
  const query = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api<Project>(`/projects/${projectId}`),
    refetchOnWindowFocus: "always",
  });
  if (query.error)
    return (
      <section className="panel chart-access-error">
        <h2>暂时无法打开此图表</h2>
        <Notice>{query.error.message}</Notice>
        {user && (
          <p>
            当前登录：<strong>{user.full_name || user.email}</strong>（
            {user.email}） · {user.is_superuser ? "管理员" : "项目用户"}
          </p>
        )}
        <p>
          二维码不会自动授予工程权限。请工程创建人或管理员将你的账号加入工程，或切换到已授权账号；若工程已删除，请从现有工程重新获取二维码。
        </p>
        <div className="chart-qr-actions">
          <Button
            kind="primary"
            onClick={() => {
              rememberLoginDestination();
              sessionStorage.removeItem("monitoring_token");
              cache.clear();
              window.location.assign("/login");
            }}
          >
            切换账号并返回此图表
          </Button>
          <Button busy={query.isFetching} onClick={() => query.refetch()}>
            重新加载
          </Button>
          <Link to="/" className="button">
            返回我的项目
          </Link>
        </div>
      </section>
    );
  if (!query.data) return <div className="loading">正在读取工程图表…</div>;
  if (!query.data.permissions.includes("database_charts"))
    return (
      <section className="panel chart-access-error">
        <Notice>当前账号没有数据库图表权限，请联系管理员。</Notice>
        <Link
          to="/projects/$projectId"
          params={{ projectId }}
          className="button"
        >
          返回工程
        </Link>
      </section>
    );
  return (
    <section className="database-page">
      <Link
        to="/projects/$projectId"
        params={{ projectId }}
        className="back-link"
      >
        ← 返回工程
      </Link>
      <div className="page-heading">
        <div>
          <h1>{query.data.name}</h1>
          <p>测项图表 · 设置自动保存到当前登录账号</p>
        </div>
      </div>
      {measurement ? (
        <ChartCard
          key={measurement}
          project={query.data}
          measurementKey={measurement}
        />
      ) : (
        <Notice>二维码缺少测项信息，请从工程的数据库图表页重新获取。</Notice>
      )}
    </section>
  );
}
