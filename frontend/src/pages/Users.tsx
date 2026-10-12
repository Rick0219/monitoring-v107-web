import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "@tanstack/react-router";
import { Plus, Users as UsersIcon, ShieldCheck } from "lucide-react";
import { api, json, type User } from "../api";
import { Button, Field, Modal, Notice, useAction } from "../components/Common";
import {
  PermissionPicker,
  allPermissions,
  permissionNames,
} from "../components/PermissionPicker";
export function Users() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/users/me"),
  });
  const query = useQuery({
    queryKey: ["users"],
    queryFn: () => api<{ data: User[]; count: number }>("/users/"),
    enabled: !!me.data?.is_superuser,
  });
  const [show, setShow] = useState(false),
    [edit, setEdit] = useState<User | null>(null),
    [name, setName] = useState(""),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [role, setRole] = useState(false);
  const action = useAction(),
    cache = useQueryClient();
  const [permissions, setPermissions] = useState<string[]>([
    "database_data",
    "database_charts",
    "analysis",
  ]);
  if (me.data && !me.data.is_superuser) return <Navigate to="/" />;
  const open = (user: User | null) => {
    setEdit(user);
    setName(user?.full_name || "");
    setEmail(user?.email || "");
    setRole(user?.is_superuser || false);
    setPermissions(
      user?.permissions || ["database_data", "database_charts", "analysis"],
    );
    setPassword("");
    action.setError("");
    setShow(true);
  };
  return (
    <>
      <section className="page-heading">
        <div>
          <span className="eyebrow">ADMINISTRATION</span>
          <h1>用户管理</h1>
          <p>为项目人员创建账号，管理角色和登录状态。</p>
        </div>
        <Button kind="primary" onClick={() => open(null)}>
          <Plus size={17} />
          新建用户
        </Button>
      </section>
      <Notice>{action.error || query.error?.message}</Notice>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              <UsersIcon size={20} />
              账号列表 <span className="count">{query.data?.count || 0}</span>
            </h2>
            <p>账号只能进入自己创建或加入的工程，工程内功能由管理员授权。</p>
          </div>
          <ShieldCheck className="muted" />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>默认功能权限</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {query.data?.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    <strong>{u.full_name || "未填写姓名"}</strong>
                  </td>
                  <td>{u.email}</td>
                  <td>
                    <span className="pill">
                      {u.is_superuser ? "管理员" : "项目用户"}
                    </span>
                  </td>
                  <td>
                    <span className="permission-summary">
                      {u.is_superuser
                        ? "全部功能"
                        : permissionNames(u.permissions)}
                    </span>
                  </td>
                  <td>
                    <span
                      className={
                        "status-dot " + (u.is_active ? "" : "inactive")
                      }
                    />
                    {u.is_active ? "正常" : "已停用"}
                  </td>
                  <td>
                    <div className="toolbar-group">
                      <button className="text-button" onClick={() => open(u)}>
                        编辑 / 重设密码
                      </button>
                      {u.id !== me.data?.id && (
                        <button
                          disabled={action.busy}
                          className={
                            "text-button " + (u.is_active ? "danger-text" : "")
                          }
                          onClick={() => {
                            if (
                              confirm(
                                (u.is_active ? "停用" : "启用") +
                                  "账号 " +
                                  u.email +
                                  "？",
                              )
                            )
                              action.run(async () => {
                                await api(
                                  "/users/" + u.id,
                                  json({ is_active: !u.is_active }, "PATCH"),
                                );
                                await cache.invalidateQueries({
                                  queryKey: ["users"],
                                });
                              });
                          }}
                        >
                          {u.is_active ? "停用" : "启用"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {show && (
        <Modal
          title={edit ? "编辑用户" : "新建用户"}
          onClose={() => setShow(false)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.run(async () => {
                await api(
                  edit ? "/users/" + edit.id : "/users/",
                  json(
                    {
                      email,
                      full_name: name,
                      is_superuser: role,
                      permissions: role ? allPermissions : permissions,
                      ...(password ? { password } : {}),
                    },
                    edit ? "PATCH" : "POST",
                  ),
                );
                await cache.invalidateQueries({ queryKey: ["users"] });
                await cache.invalidateQueries({ queryKey: ["me"] });
                setShow(false);
              });
            }}
          >
            <Field label="姓名">
              <input
                autoFocus
                required
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="邮箱">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
            <Field
              label={
                edit ? "新密码（留空则保持原密码）" : "初始密码（至少 8 位）"
              }
            >
              <input
                type="password"
                minLength={8}
                maxLength={128}
                required={!edit}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Field label="账号角色">
              <select
                value={role ? "admin" : "user"}
                disabled={edit?.id === me.data?.id}
                onChange={(e) => setRole(e.target.value === "admin")}
              >
                <option value="user">项目用户</option>
                <option value="admin">管理员</option>
              </select>
            </Field>
            {!role && (
              <>
                <PermissionPicker
                  value={permissions}
                  onChange={setPermissions}
                  disabled={action.busy}
                />
                <p className="muted">
                  作为各工程的默认权限；管理员可在工程成员中单独调整。仅开放勾选的页面和操作。
                </p>
              </>
            )}
            <Notice>{action.error}</Notice>
            <div className="modal-actions">
              <Button type="button" onClick={() => setShow(false)}>
                取消
              </Button>
              <Button kind="primary" busy={action.busy}>
                保存账号
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
