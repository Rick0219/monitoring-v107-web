import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api, type Project } from "../api";
import { Button, Modal, Notice, useAction } from "./Common";

export function DeleteProject({
  project,
  onDeleted,
}: {
  project: Project;
  onDeleted?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const action = useAction(),
    cache = useQueryClient();
  return (
    <>
      <Button
        kind="danger"
        onClick={() => setOpen(true)}
        aria-label={`删除工程 ${project.name}`}
      >
        <Trash2 size={16} />
        删除工程
      </Button>
      {open && (
        <Modal
          title="确认删除工程"
          onClose={() => !action.busy && setOpen(false)}
        >
          <p>
            确定删除工程“<strong>{project.name}</strong>”？
          </p>
          <p className="muted">
            删除后，所有成员都将无法访问该工程的数据、图表、资料和报告，工程不会再出现在项目列表中。请先导出需要保留的数据。
          </p>
          <Notice>{action.error}</Notice>
          <div className="modal-actions">
            <Button disabled={action.busy} onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              kind="danger"
              busy={action.busy}
              onClick={() =>
                action.run(async () => {
                  await api(
                    `/projects/${project.id}?revision=${project.revision}`,
                    { method: "DELETE" },
                  );
                  setOpen(false);
                  await cache.invalidateQueries({ queryKey: ["projects"] });
                  onDeleted?.();
                })
              }
            >
              确认删除
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
