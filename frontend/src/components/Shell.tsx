import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useLocation } from "@tanstack/react-router";
import {
  Activity,
  FolderOpen,
  Users,
  LayoutGrid,
  LogOut,
  KeyRound,
  Menu,
  ShieldCheck,
} from "lucide-react";
import { api, json, token, type User } from "../api";
import { Button, Field, Modal, Notice, useAction } from "./Common";
export function Shell() {
  const query = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/users/me"),
    enabled: !!token(),
    retry: false,
  });
  const [passwordDialog, setPasswordDialog] = useState(false),
    [open, setOpen] = useState(false);
  const [old, setOld] = useState(""),
    [next, setNext] = useState(""),
    action = useAction();
  const cache = useQueryClient(),
    location = useLocation();
  if (!token()) {
    return <div className="loading"><a href="/login">请重新登录</a></div>;
  }
  if (query.isPending) return <div className="loading">正在加载工作空间…</div>;
  if (query.error)
    return (
      <div className="loading">
        <Notice>{query.error.message}</Notice>
        <Button
          onClick={() => {
            sessionStorage.removeItem("monitoring_token");
            cache.clear();
            window.location.assign("/login");
          }}
        >
          重新登录
        </Button>
      </div>
    );
  const user = query.data!;
  const nav = [
    { to: "/", icon: FolderOpen, label: "我的项目" },
    ...(user.is_superuser
      ? [
          { to: "/all-projects", icon: LayoutGrid, label: "全部项目" },
          { to: "/users", icon: Users, label: "用户管理" },
        ]
      : []),
  ];
  return (
    <div className="app">
      <aside className={"sidebar " + (open ? "open" : "")}>
        <Link to="/" className="brand">
          <span className="brand-icon">
            <Activity />
          </span>
          <span>
            监测工作台<small>V1.07 · WEB</small>
          </span>
        </Link>
        <div className="nav-caption">工作空间</div>
        <nav>
          {nav.map((n) => (
            <Link
              key={n.to}
              to={n.to}
              onClick={() => setOpen(false)}
              className={
                "nav-item " +
                (location.pathname === n.to ||
                (n.to === "/" && location.pathname.startsWith("/projects"))
                  ? "active"
                  : "")
              }
            >
              <n.icon size={19} />
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="secure-note">
            <ShieldCheck size={16} />
            <span>
              工程归属与访问权限
              <br />
              由服务端统一校验
            </span>
          </div>
          <div className="account">
            <span className="avatar">
              {(user.full_name || user.email).slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{user.full_name || user.email}</strong>
              <small>{user.is_superuser ? "管理员" : "项目用户"}</small>
            </div>
          </div>
          <div className="account-actions">
            <button onClick={() => setPasswordDialog(true)}>
              <KeyRound size={15} />
              修改密码
            </button>
            <button
              onClick={() => {
                sessionStorage.removeItem("monitoring_token");
                cache.clear();
                window.location.assign("/login");
              }}
            >
              <LogOut size={15} />
              退出
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="打开导航"
            onClick={() => setOpen(!open)}
          >
            <Menu />
          </button>
          <span>
            工程监测 /{" "}
            <strong>
              {location.pathname === "/users"
                ? "用户管理"
                : location.pathname === "/all-projects"
                  ? "全部项目"
                  : location.pathname.startsWith("/projects")
                    ? "项目工作空间"
                    : "我的项目"}
            </strong>
          </span>
          <span className="pill">
            {user.is_superuser ? "管理员" : "项目用户"}
          </span>
        </header>
        <main className="content">
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>监测数据整理与日报生成软件</span>
          <span>V1.07 Web</span>
        </footer>
      </div>
      {passwordDialog && (
        <Modal title="修改登录密码" onClose={() => setPasswordDialog(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.run(async () => {
                await api(
                  "/users/me/password",
                  json({ current_password: old, new_password: next }, "PATCH"),
                );
                setOld("");
                setNext("");
              }, "密码修改成功");
            }}
          >
            <Field label="原密码">
              <input
                type="password"
                required
                value={old}
                onChange={(e) => setOld(e.target.value)}
              />
            </Field>
            <Field label="新密码（至少 8 位）">
              <input
                type="password"
                minLength={8}
                maxLength={128}
                required
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            </Field>
            <Notice>{action.error}</Notice>
            <Notice success>{action.success}</Notice>
            <Button kind="primary" busy={action.busy}>
              保存密码
            </Button>
          </form>
        </Modal>
      )}
    </div>
  );
}
