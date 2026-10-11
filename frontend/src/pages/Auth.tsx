import { useState } from "react";
import { takeLoginDestination, peekLoginDestination } from "../authNavigation";
import {
  Activity,
  ArrowRight,
  Database,
  FileChartColumn,
  ShieldCheck,
} from "lucide-react";
import { api } from "../api";
import { Button, Field, Notice, useAction } from "../components/Common";
export function Login() {
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const action = useAction();
  return (
    <main className="login-page">
      <aside className="login-story">
        <div className="brand">
          <Activity />
          <span>
            监测工作台 <small>V1.07 · WEB</small>
          </span>
        </div>
        <div>
          <span className="eyebrow">ENGINEERING MONITORING</span>
          <h1>
            让每一次监测，
            <br />
            成为有据可循的判断。
          </h1>
          <p>
            从工程数据到分析结论，
            <br />
            在同一个工作空间完成。
          </p>
          <div className="story-points">
            <span>
              <Database /> 统一管理工程数据
            </span>
            <span>
              <FileChartColumn /> 分析与日报连贯完成
            </span>
            <span>
              <ShieldCheck /> 按账号隔离项目资料
            </span>
          </div>
        </div>
        <small>数据有序 · 分析有据 · 报告可追溯</small>
      </aside>
      <section className="login-form">
        <div>
          <span className="eyebrow">欢迎回来</span>
          <h2>登录监测工作台</h2>
          <p className="muted">
            {peekLoginDestination().startsWith("/charts/")
              ? "请使用该工程创建人、成员或管理员账号登录，登录后返回刚才扫码的图表。"
              : "使用管理员为你分配的账号，进入我的项目。"}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.run(async () => {
                const result = await api("/login/access-token", {
                  method: "POST",
                  body: new URLSearchParams({ username: email, password }),
                });
                sessionStorage.setItem("monitoring_token", result.access_token);
                window.location.assign(takeLoginDestination());
              });
            }}
          >
            <Field label="邮箱">
              <input
                autoFocus
                type="email"
                autoComplete="username"
                required
                placeholder="请输入账号邮箱"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
            <Field label="密码">
              <input
                type="password"
                autoComplete="current-password"
                required
                placeholder="请输入密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Notice>{action.error}</Notice>
            <Button type="submit" busy={action.busy} kind="primary full">
              登录 <ArrowRight size={17} />
            </Button>
          </form>
          <p className="login-help">没有账号或忘记密码？请联系系统管理员。</p>
        </div>
        <small className="muted">监测数据整理与日报生成软件 · 网页版</small>
      </section>
    </main>
  );
}
