import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const env = Object.fromEntries(
  fs
    .readFileSync(path.resolve("../.env"), "utf8")
    .split(/\r?\n/)
    .filter((l) => l.includes("=") && !l.startsWith("#"))
    .map((l) => {
      const i = l.indexOf("=");
      let value = l.slice(i + 1);
      try {
        value = JSON.parse(value);
      } catch {}
      return [l.slice(0, i), value];
    }),
);

test("管理员分配三类功能权限，项目只显示允许页面并可单独覆盖", async ({
  page,
  browser,
  request,
}) => {
  if (!process.env.WEB_TEST_URL?.includes(":8017"))
    throw new Error("Use isolated port 8017");
  const auth = await request.post("/api/v1/login/access-token", {
    form: {
      username: env.FIRST_SUPERUSER,
      password: env.FIRST_SUPERUSER_PASSWORD,
    },
  });
  const token = (await auth.json()).access_token,
    headers = { Authorization: "Bearer " + token };
  const project = await (
    await request.post("/api/v1/projects", {
      headers,
      data: { name: "权限分类验收 " + Date.now() },
    })
  ).json();
  await request.put(`/api/v1/projects/${project.id}/data`, {
    headers,
    data: {
      revision: 1,
      measurement_key: "level:沉降",
      rows: [
        { 点号: "A", 时间: "2026-01-01", 测量值: 10 },
        { 点号: "A", 时间: "2026-01-03", 测量值: 9.99 },
      ],
    },
  });
  await page.addInitScript(
    (t) => sessionStorage.setItem("monitoring_token", t),
    token,
  );
  const password = "Permissions-test-123!";
  for (const [preset, tabs] of [
    ["查看与分析", ["数据库数据", "数据库图表", "智能分析"]],
    ["数据编辑", ["数据录入", "数据库数据"]],
    ["仅报告", ["报告生成"]],
  ] as const) {
    const email = `permissions-${Date.now()}@example.com`;
    await page.goto("/users");
    await page.getByRole("button", { name: "新建用户", exact: true }).click();
    await page.getByLabel("姓名", { exact: true }).fill("权限验收 " + preset);
    await page.getByLabel("邮箱", { exact: true }).fill(email);
    await page.getByLabel("初始密码", { exact: false }).fill(password);
    await expect(page.locator(".permission-checks label")).toHaveText([
      "数据录入",
      "数据库数据",
      "数据库图表",
      "智能分析",
      "报告生成",
    ]);
    await page.getByRole("button", { name: preset, exact: true }).click();
    if (preset === "查看与分析")
      await page.screenshot({
        path: "../docs/screenshots/account-permissions.png",
        fullPage: true,
      });
    await page.getByRole("button", { name: "保存账号" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.goto(`/projects/${project.id}`);
    await page.getByRole("button", { name: "工程成员", exact: true }).click();
    await page.getByLabel("成员账号邮箱").fill(email);
    await page.getByRole("button", { name: "添加成员", exact: true }).click();
    const row = page.locator(".project-members li").filter({ hasText: email });
    await expect(row).toBeVisible();
    const context = await browser.newContext();
    const member = await context.newPage();
    await member.goto(`/projects/${project.id}`);
    await member.getByLabel("邮箱", { exact: true }).fill(email);
    await member.getByLabel("密码", { exact: true }).fill(password);
    await member.getByRole("button", { name: "登录", exact: true }).click();
    const workspaceTabs = member.getByRole("tablist", { name: "工程功能" });
    await expect(workspaceTabs.getByRole("tab")).toHaveText([...tabs]);
    if (preset === "查看与分析") {
      await expect(
        member.getByRole("button", { name: "编辑当日数据" }),
      ).toHaveCount(0);
      await member.getByRole("tab", { name: "智能分析", exact: true }).click();
      await member.getByRole("button", { name: /项目资料/ }).click();
      await expect(member.getByText("上传并解析", { exact: true })).toHaveCount(
        0,
      );
      await member.getByRole("button", { name: "关闭", exact: true }).click();
      await member
        .getByRole("button", { name: "计算分析", exact: true })
        .click();
      await expect(
        member.getByRole("cell", { name: "-10", exact: true }).first(),
      ).toBeVisible();
      await row.getByRole("button", { name: "设置权限" }).click();
      await page.getByLabel("使用账号默认权限").uncheck();
      await page.getByRole("button", { name: "仅报告", exact: true }).click();
      await page.getByRole("button", { name: "保存工程权限" }).click();
      await expect(
        page.getByRole("button", { name: "保存工程权限" }),
      ).toHaveCount(0);
      await member.reload();
      await expect(workspaceTabs.getByRole("tab")).toHaveText(["报告生成"]);
    } else if (preset === "数据编辑") {
      await member
        .getByRole("tab", { name: "数据库数据", exact: true })
        .click();
      await member.getByRole("button", { name: "编辑当日数据" }).click();
      await member.getByLabel("第1行 测量值", { exact: true }).fill("9.98");
      await member.getByRole("button", { name: "保存当日数据" }).click();
      await expect(member.getByRole("dialog")).toHaveCount(0);
      await expect(
        member.getByRole("cell", { name: "-20", exact: true }).first(),
      ).toBeVisible();
    } else {
      await member
        .getByRole("button", { name: "预览报告", exact: true })
        .click();
      await expect(
        member.getByRole("button", { name: "导出预览范围 Excel", exact: true }),
      ).toBeEnabled();
      const downloaded = member.waitForEvent("download");
      await member
        .getByRole("button", { name: "导出预览范围 Excel", exact: true })
        .click();
      expect((await downloaded).suggestedFilename()).toMatch(/\.xlsx$/);
    }
    await context.close();
  }
});

for (const [permission, label] of [
  ["data_entry", "数据录入"],
  ["database_data", "数据库数据"],
  ["database_charts", "数据库图表"],
  ["analysis", "智能分析"],
  ["reports", "报告生成"],
] as const) {
  test(`只授权${label}时只显示该入口，扫码也遵守图表权限`, async ({
    page,
    request,
  }) => {
    if (!process.env.WEB_TEST_URL?.includes(":8017"))
      throw new Error("Use isolated port 8017");
    const admin = await request.post("/api/v1/login/access-token", {
      form: {
        username: env.FIRST_SUPERUSER,
        password: env.FIRST_SUPERUSER_PASSWORD,
      },
    });
    const headers = {
      Authorization: "Bearer " + (await admin.json()).access_token,
    };
    const email = `single-${permission}-${Date.now()}@example.com`,
      password = "Single-permission-123!";
    const created = await request.post("/api/v1/users/", {
      headers,
      data: { email, password, permissions: [permission] },
    });
    expect(created.ok()).toBeTruthy();
    const project = await (
      await request.post("/api/v1/projects", {
        headers,
        data: { name: "单功能验收 " + label + Date.now() },
      })
    ).json();
    expect(
      (
        await request.put(`/api/v1/projects/${project.id}/data`, {
          headers,
          data: {
            revision: 1,
            measurement_key: "level:沉降",
            rows: [
              { 点号: "A", 时间: "2026-01-01", 测量值: 10 },
              { 点号: "A", 时间: "2026-01-03", 测量值: 9.99 },
            ],
          },
        })
      ).ok(),
    ).toBeTruthy();
    expect(
      (
        await request.post(`/api/v1/projects/${project.id}/members`, {
          headers,
          data: { email },
        })
      ).ok(),
    ).toBeTruthy();
    const auth = await request.post("/api/v1/login/access-token", {
      form: { username: email, password },
    });
    await page.addInitScript(
      (t) => sessionStorage.setItem("monitoring_token", t),
      (await auth.json()).access_token,
    );
    const requested: string[] = [];
    page.on("request", (r) => requested.push(new URL(r.url()).pathname));
    await page.goto(`/projects/${project.id}`);
    await expect(
      page.getByRole("tablist", { name: "工程功能" }).getByRole("tab"),
    ).toHaveText([label]);
    await expect(
      page.getByRole("button", { name: "导入工程", exact: true }),
    ).toHaveCount(permission === "data_entry" ? 1 : 0);
    await expect(
      page.getByRole("button", { name: "导出工程", exact: true }),
    ).toHaveCount(permission === "data_entry" ? 1 : 0);
    await expect(
      page.getByRole("button", { name: "工程设置", exact: true }),
    ).toHaveCount(permission === "data_entry" ? 1 : 0);
    await expect(
      page.getByRole("button", { name: "工程成员", exact: true }),
    ).toHaveCount(0);
    if (permission === "database_data") {
      await expect(
        page.getByRole("cell", { name: "-10", exact: true }).first(),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "编辑当日数据" }),
      ).toHaveCount(0);
      await page.getByLabel("数据库日期").selectOption("2026-01-01");
      await page.getByLabel("数据内容").selectOption("raw");
      await expect(
        page.getByRole("cell", { name: "2026-01-01", exact: true }),
      ).toBeVisible();
      expect(
        requested.some(
          (p) => p.endsWith("/charts") || p.endsWith("/chart-link"),
        ),
      ).toBeFalsy();
    } else if (permission === "database_charts") {
      await expect(page.locator(".database-chart-card")).toHaveCount(1);
      await page.getByLabel("图表形式").selectOption("history");
      await expect(page.getByText("已保存，下次进入自动恢复")).toBeVisible();
      expect(
        requested.some((p) => p.endsWith("/data") || p.endsWith("/database")),
      ).toBeFalsy();
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({
        path: "../docs/screenshots/chart-only-permission-mobile.png",
        fullPage: true,
      });
    }
    await page.goto(
      `/charts/${project.id}?measurement=${encodeURIComponent("level:沉降")}`,
    );
    if (permission === "database_charts") {
      await expect(page.locator(".database-chart-card")).toHaveCount(1);
      await expect(page.getByLabel("图表形式")).toHaveValue("history");
    } else {
      await expect(
        page.getByText("当前账号没有数据库图表权限，请联系管理员。"),
      ).toBeVisible();
      await expect(page.locator(".database-chart-card")).toHaveCount(0);
    }
    await page.goto("/");
    await expect(
      page.getByRole("button", { name: "新建工程", exact: true }),
    ).toHaveCount(permission === "data_entry" ? 1 : 0);
  });
}
