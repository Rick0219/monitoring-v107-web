import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json, type User } from "../api";
import { Button, Field, Modal, Notice, useAction } from "./Common";
import { PermissionPicker, permissionNames } from "./PermissionPicker";

type Member = User & { is_owner: boolean; inherits_permissions: boolean };

export function ProjectMembers({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const url = `/projects/${projectId}/members`;
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["project-members", projectId],
    queryFn: () => api<{ data: Member[]; count: number }>(url),
  });
  const [email, setEmail] = useState("");
  const [inherit, setInherit] = useState(true);
  const [permissions, setPermissions] = useState<string[]>([
    "database_data",
    "database_charts",
    "analysis",
  ]);
  const [editing, setEditing] = useState<Member | null>(null);
  const admin = !!cache.getQueryData<User>(["me"])?.is_superuser;
  const action = useAction();
  const refresh = async () => {
    await cache.invalidateQueries({ queryKey: ["project-members", projectId] });
    await cache.invalidateQueries({ queryKey: ["projects"] });
    await cache.invalidateQueries({ queryKey: ["project", projectId] });
  };
  return (
    <Modal title="工程成员" onClose={onClose}>
      <p className="muted">
        成员按管理员授予的功能权限访问工程。每个账号单独保存图表显示设置。
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action.run(
            async () => {
              if (editing) {
                await api(
                  url + "/" + editing.id + "/permissions",
                  json({ permissions: inherit ? null : permissions }, "PATCH"),
                );
                setEditing(null);
              } else {
                await api(
                  url,
                  json({
                    email,
                    ...(admin && !inherit ? { permissions } : {}),
                  }),
                );
              }
              setEmail("");
              await refresh();
            },
            editing
              ? "工程权限已更新"
              : "账号已加入工程，成员登录后可在“我的项目”中看到此工程。",
          );
        }}
      >
        <Field label="成员账号邮箱">
          <input
            type="email"
            required
            disabled={!!editing}
            maxLength={255}
            placeholder="填写已有账号的登录邮箱"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        {admin && (
          <>
            <label className="permission-inherit">
              <input
                type="checkbox"
                checked={inherit}
                onChange={(e) => setInherit(e.target.checked)}
              />
              使用账号默认权限
            </label>
            {!inherit && (
              <PermissionPicker
                value={permissions}
                onChange={setPermissions}
                disabled={action.busy}
              />
            )}
          </>
        )}
        <div className="modal-actions">
          {editing && (
            <Button
              type="button"
              onClick={() => {
                setEditing(null);
                setEmail("");
                setInherit(true);
              }}
            >
              取消编辑
            </Button>
          )}
          <Button kind="primary" busy={action.busy}>
            {editing ? "保存工程权限" : "添加成员"}
          </Button>
        </div>
      </form>
      <Notice>{action.error || query.error?.message}</Notice>
      <Notice success>{action.success}</Notice>
      {query.isPending ? (
        <p className="muted">正在加载工程成员…</p>
      ) : (
        <ul className="project-members">
          {query.data?.data.map((member) => (
            <li key={member.id}>
              <div className="member-identity">
                <strong>{member.full_name || member.email}</strong>
                <span>{member.email}</span>
                <small>
                  {member.is_owner ? "工程创建人" : "工程成员"}
                  {member.is_superuser ? " · 系统管理员" : ""}
                  {!member.is_active ? " · 已停用" : ""}
                </small>
                <small>
                  {member.is_superuser
                    ? "全部功能"
                    : permissionNames(member.permissions)}
                  {!member.is_superuser &&
                    (member.inherits_permissions
                      ? "（账号默认）"
                      : "（本工程单独设置）")}
                </small>
              </div>
              <div className="member-actions">
                {admin && !member.is_superuser && (
                  <Button
                    onClick={() => {
                      setEditing(member);
                      setEmail(member.email);
                      setPermissions(member.permissions);
                      setInherit(member.inherits_permissions);
                    }}
                  >
                    设置权限
                  </Button>
                )}
                {!member.is_owner && (
                  <Button
                    kind="danger"
                    busy={action.busy}
                    onClick={() => {
                      if (
                        !confirm(
                          `将“${member.full_name || member.email}”移出此工程？${member.is_superuser ? "系统管理员仍可访问全部工程。" : "移除后，该账号不能再访问此工程或扫码图表。"}`,
                        )
                      )
                        return;
                      action.run(async () => {
                        await api(url + "/" + member.id, { method: "DELETE" });
                        await refresh();
                      }, "成员已移除");
                    }}
                  >
                    移除
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        新账号需先在“用户管理”中创建。创建人可添加或移除成员；只有管理员可以设置权限。系统管理员始终可访问全部工程。
      </p>
    </Modal>
  );
}
