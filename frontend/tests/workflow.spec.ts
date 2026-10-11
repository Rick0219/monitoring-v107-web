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
async function login(page: any, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "我的项目", exact: true }),
  ).toBeVisible();
}
test("管理员和普通用户完整工程工作流", async ({ page, browser, request }) => {
  const suffix = Date.now().toString(),
    email = "webtest" + suffix + "@example.com",
    password = "Browser-test-123!";
  await login(page, env.FIRST_SUPERUSER, env.FIRST_SUPERUSER_PASSWORD);
  await expect(
    page.getByRole("link", { name: "全部项目", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "用户管理", exact: true }).click();
  await page.getByRole("button", { name: "新建用户" }).click();
  await page.getByLabel("姓名", { exact: true }).fill("验收用户");
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("初始密码").fill(password);
  await page.getByRole("button", { name: "全部功能", exact: true }).click();
  await page.getByRole("button", { name: "保存账号" }).click();
  await expect(
    page.getByRole("cell", { name: email, exact: true }),
  ).toBeVisible();
  const context = await browser.newContext(),
    userPage = await context.newPage();
  userPage.on("pageerror", (e) => console.log("UI ERROR", e.message));
  await login(userPage, email, password);
  await expect(
    userPage.getByRole("link", { name: "用户管理", exact: true }),
  ).toHaveCount(0);
  await expect(
    userPage.getByRole("link", { name: "全部项目", exact: true }),
  ).toHaveCount(0);
  await userPage.getByRole("button", { name: "新建工程" }).click();
  await userPage
    .getByLabel("工程名称", { exact: true })
    .fill("网页验收工程 " + suffix);
  await userPage.getByLabel("工程位置", { exact: true }).fill("佛山");
  await userPage.getByRole("button", { name: "创建并进入工程" }).click();
  await expect(
    userPage.getByRole("heading", {
      name: "网页验收工程 " + suffix,
      exact: true,
    }),
  ).toBeVisible();
  await userPage.getByRole("button", { name: "水准", exact: true }).click();
  await userPage.getByLabel("监测日期", { exact: true }).fill("2026-01-01");
  await userPage.getByRole("button", { name: "新增一行" }).click();
  await userPage.getByLabel("第1行 点号", { exact: true }).fill("JGC-01");
  await userPage.getByLabel("第1行 测量值", { exact: true }).fill("10");
  await userPage.getByRole("button", { name: "保存数据" }).click();
  await expect(userPage.getByText("数据已保存到当前工程")).toBeVisible();
  await userPage.getByLabel("监测日期", { exact: true }).fill("2026-01-03");
  await userPage.getByRole("button", { name: "复制已有点号" }).click();
  await userPage.getByLabel("第1行 测量值", { exact: true }).fill("9.99");
  await userPage.getByRole("button", { name: "保存数据" }).click();
  await expect(userPage.getByText("数据已保存到当前工程")).toBeVisible();
  await userPage.getByLabel("第1行 测量值", { exact: true }).fill("9.98");
  await userPage.getByRole("button", { name: "工程设置", exact: true }).click();
  await userPage
    .getByLabel("工程位置", { exact: true })
    .fill("佛山 · 验收区段");
  await userPage.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(
    userPage.getByLabel("第1行 测量值", { exact: true }),
  ).toHaveValue("9.98");
  userPage.once("dialog", (dialog) => dialog.dismiss());
  await userPage.getByRole("link", { name: "我的项目", exact: true }).click();
  await expect(
    userPage.getByLabel("第1行 测量值", { exact: true }),
  ).toHaveValue("9.98");
  await userPage.getByLabel("第1行 测量值", { exact: true }).fill("9.99");
  await userPage.getByRole("button", { name: "保存数据" }).click();
  await expect(
    userPage.getByRole("button", { name: "保存数据" }),
  ).toBeDisabled();
  await userPage.getByRole("tab", { name: "智能分析" }).click();
  await userPage
    .getByLabel("分析测项", { exact: true })
    .selectOption("level:建筑物位移");
  await userPage.getByRole("button", { name: "计算分析" }).click();
  await expect(
    userPage.getByRole("cell", { name: "-10", exact: true }).first(),
  ).toBeVisible();
  await userPage.screenshot({
    path: "../docs/screenshots/analysis.png",
    fullPage: true,
  });
  await userPage.getByRole("tab", { name: "报告生成" }).click();
  await userPage.getByRole("button", { name: "预览报告" }).click();
  await expect(userPage.getByText("MONITORING REPORT")).toBeVisible();
  const event = userPage.waitForEvent("download");
  await userPage.getByRole("button", { name: "导出预览范围 Excel" }).click();
  const file = await event;
  expect(file.suggestedFilename()).toContain("监测日报.xlsx");
  await userPage.getByRole("link", { name: "返回我的项目" }).click();
  await expect(userPage.getByText("已录入数据", { exact: true })).toBeVisible();
  await expect(userPage.getByText("Invalid Date", { exact: true })).toHaveCount(
    0,
  );
  await userPage.screenshot({
    path: "../docs/screenshots/my-projects.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "全部项目", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "网页验收工程 " + suffix }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/admin-projects.png",
    fullPage: true,
  });
  await userPage.setViewportSize({ width: 390, height: 844 });
  await expect(
    userPage.getByRole("heading", { name: "我的项目", exact: true }),
  ).toBeVisible();
  expect(
    await userPage.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await userPage.screenshot({
    path: "../docs/screenshots/mobile-projects.png",
    fullPage: true,
  });
  await context.close();
});
