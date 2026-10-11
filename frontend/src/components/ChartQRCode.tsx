import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { QrCode, Download, ExternalLink, Copy } from "lucide-react";
import { api, saveText } from "../api";
import { Button, Modal, Notice, useAction } from "./Common";

type ChartLink = { url: string | null; network: string; message: string };
export function ChartQRCode({
  projectId,
  measurementKey,
  label,
}: {
  projectId: string;
  measurementKey: string;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const action = useAction(),
    svgRef = useRef<HTMLDivElement>(null);
  const query = useQuery({
    queryKey: ["chart-link", projectId, measurementKey],
    queryFn: () =>
      api<ChartLink>(
        `/projects/${projectId}/chart-link?measurement_key=${encodeURIComponent(measurementKey)}`,
      ),
    staleTime: 60000,
  });
  const url = query.data?.url;
  return (
    <>
      <button
        className="chart-qr-mini"
        aria-label={`放大二维码 · ${label}`}
        title="扫码查看图表和修改配置"
        onClick={() => {
          setOpen(true);
          query.refetch();
        }}
      >
        {url ? (
          <QRCodeSVG
            value={url}
            size={104}
            marginSize={4}
            level="M"
            title={`${label}图表二维码`}
          />
        ) : (
          <QrCode size={44} />
        )}
        <span>
          {url
            ? "扫码查看 / 配置"
            : query.isPending
              ? "生成二维码…"
              : "扫码访问设置"}
        </span>
      </button>
      {open && (
        <Modal title={`图表二维码 · ${label}`} onClose={() => setOpen(false)}>
          <Notice>{query.error?.message}</Notice>
          {url && (
            <div className="chart-qr-large" ref={svgRef}>
              <QRCodeSVG
                value={url}
                size={280}
                marginSize={4}
                level="M"
                title={`${label}图表二维码`}
              />
            </div>
          )}
          <p className="chart-qr-help">
            {query.data?.message || "正在获取图表地址…"}
          </p>
          <p className="muted">
            仅工程创建人、成员和管理员可访问。扫码登录后，直接显示该测项；修改会保存到当前登录账号的图表设置。
          </p>
          {url && (
            <>
              <label className="field">
                图表访问地址
                <input
                  aria-label="图表访问地址"
                  value={url}
                  readOnly
                  onFocus={(e) => e.target.select()}
                />
              </label>
              <div className="chart-qr-actions">
                <Button
                  onClick={() =>
                    action.run(async () => {
                      if (!navigator.clipboard)
                        throw new Error(
                          "当前浏览器不支持自动复制，请选中上方地址后手动复制。",
                        );
                      await navigator.clipboard.writeText(url);
                    }, "链接已复制")
                  }
                >
                  <Copy size={16} />
                  复制链接
                </Button>
                <Button
                  onClick={() => {
                    const svg = svgRef.current?.querySelector("svg");
                    if (svg)
                      saveText(
                        svg.outerHTML,
                        `${label}-图表二维码.svg`,
                        "image/svg+xml;charset=utf-8",
                      );
                  }}
                >
                  <Download size={16} />
                  下载二维码
                </Button>
                <a
                  className="button"
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ExternalLink size={16} />
                  打开图表
                </a>
              </div>
            </>
          )}
          <Notice>{action.error}</Notice>
          <Notice success>{action.success}</Notice>
        </Modal>
      )}
    </>
  );
}
