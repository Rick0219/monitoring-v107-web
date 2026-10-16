import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const env = Object.fromEntries(
  fs.readFileSync(path.resolve("../.env"), "utf8").split(/\r?\n/)
    .filter((l) => l.includes("=") && !l.startsWith("#"))
    .map((l) => {
      const i = l.indexOf("=");
      let value = l.slice(i + 1);
      try { value = JSON.parse(value); } catch { /* plain value */ }
      return [l.slice(0, i), value];
    }),
);

async function openSandbox(page: Page) {
  page.on("pageerror", (error) => console.log("PAGEERROR", error.message));
  await page.goto("/login");
  await page.getByLabel("邮箱", { exact: true }).fill(env.FIRST_SUPERUSER);
  await page.getByLabel("密码", { exact: true }).fill(env.FIRST_SUPERUSER_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我的项目", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建工程" }).click();
  const suffix = Date.now().toString();
  await page.getByLabel("工程名称", { exact: true }).fill("数字孪生验收工程 " + suffix);
  await page.getByRole("button", { name: "创建并进入工程" }).click();
  await page.waitForURL(/\/projects\/[0-9a-f-]+/);
  const projectId = new URL(page.url()).pathname.split("/")[2];
  const seedStatus = await page.evaluate(async (id) => {
    const token = sessionStorage.getItem("monitoring_token");
    const response = await fetch("/api/v1/projects/" + id + "/data", {
      method: "PUT",
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: JSON.stringify({ revision: 1, measurement_key: "level:建筑物位移", rows: [{ "时间": "2026-01-01", "点号": "JGC-01", "测量值": 10 }, { "时间": "2026-01-02", "点号": "JGC-01", "测量值": 9.99 }] }),
    });
    return { status: response.status, body: await response.text() };
  }, projectId);
  expect(seedStatus.status, seedStatus.body).toBe(200);
  await page.reload();
  await page.getByRole("tab", { name: "智能分析" }).click();
  await expect(page.getByRole("heading", { name: "数字孪生 3D 沙盘", exact: true })).toBeVisible();
  await expect(page.getByLabel("上传 DWG 自动生成")).toHaveCount(1);
  const scene = path.resolve("tests/fixtures/twin-scene.json");
  await page.getByLabel("导入数字孪生场景").setInputFiles(scene);
  await expect(page.getByText("数字孪生场景已导入")).toBeVisible();
  await expect(page.getByRole("button", { name: "展开点位配置" })).toBeVisible();
  await expect(page.getByLabel("数据库点号")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "图层", exact: true })).toHaveCount(0);
  await expect(page.locator(".digital-twin-inspector")).toHaveCount(0);
  await page.getByRole("button", { name: "展开点位配置" }).click();
  await expect(page.getByRole("button", { name: /选择 JGC-01/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "图层", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /添加到沙盘/ }).click();
  return projectId;
}

test("沙盘周边放点和拖动不被结构边界截断，保存刷新后保留位置", async ({ page }) => {
  const projectId = await openSandbox(page);
  const canvas = page.getByRole("application", { name: "数字孪生三维沙盘" });
  const bounds = (await canvas.boundingBox())!;
  await canvas.click({ position: { x: bounds.width * 0.12, y: bounds.height * 0.85 } });
  const stem = canvas.locator(".digital-twin-sensor line");
  await expect(canvas.locator("text")).toHaveCount(1);
  const saveResponse = page.waitForResponse((response) => response.url().endsWith("/twin/scene") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "保存沙盘", exact: true }).click();
  const saved = await (await saveResponse).json();
  expect(saved.scene.placed_points[0].position.some((value: number) => value < 0 || value > 1)).toBe(true);
  await expect(page.getByText("数字孪生场景已保存", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "智能分析" }).click();
  await page.getByRole("button", { name: "展开点位配置" }).click();
  const marker = canvas.locator(".digital-twin-sensor circle");
  await marker.hover();
  await page.mouse.down();
  const nextBounds = (await canvas.boundingBox())!;
  await page.mouse.move(nextBounds.x + nextBounds.width * 0.85, nextBounds.y + nextBounds.height * 0.72, { steps: 12 });
  await page.mouse.up();
  const moved = { x: Number(await stem.getAttribute("x1")), y: Number(await stem.getAttribute("y1")) };
  expect(moved.x).toBeGreaterThan(40);
  expect(moved.y).toBeGreaterThan(35);
  await page.getByRole("button", { name: "保存沙盘", exact: true }).click();
  await expect(page.getByText("数字孪生场景已保存", { exact: true })).toBeVisible();
});

test("点击点位打开无滚动条的独立图表窗口，按钮缩放仍可用", async ({ page }) => {
  await openSandbox(page);
  const canvas = page.getByRole("application", { name: "数字孪生三维沙盘" });
  const bounds = (await canvas.boundingBox())!;
  await canvas.click({ position: { x: bounds.width * 0.15, y: bounds.height * 0.9 } });
  await page.getByRole("button", { name: "收起点位配置" }).click();
  const ground = canvas.locator(":scope > polygon");
  const beforeZoom = await ground.getAttribute("points");
  await page.getByRole("button", { name: "缩小沙盘" }).click();
  expect(await ground.getAttribute("points")).not.toBe(beforeZoom);
  const afterZoom = await ground.getAttribute("points");
  await canvas.hover();
  await page.mouse.wheel(0, 240);
  expect(await ground.getAttribute("points")).toBe(afterZoom);
  await canvas.locator(".digital-twin-sensor circle").click();
  const popup = page.getByRole("dialog", { name: "点位数据图表 · JGC-01", exact: true });
  await expect(popup).toBeVisible();
  await expect(popup.locator(".report-chart")).toBeVisible();
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(viewport);
    await expect.poll(() => popup.evaluate((dialog) => {
      const chart = dialog.querySelector(".report-chart");
      if (!chart) return { withinViewport: false, noOverflow: false, chartFits: false };
      const picture = chart.querySelector("canvas");
      const box = dialog.getBoundingClientRect();
      const chartBox = chart.getBoundingClientRect();
      return {
        withinViewport: box.left >= 0 && box.top >= 0 && box.right <= innerWidth && box.bottom <= innerHeight,
        noOverflow: dialog.scrollWidth <= dialog.clientWidth + 1 && dialog.scrollHeight <= dialog.clientHeight + 1,
        chartFits: chartBox.width > 0 && chartBox.height > 0 && chartBox.bottom <= box.bottom && !!picture && picture.clientWidth <= chart.clientWidth + 1 && picture.clientHeight <= chart.clientHeight + 1,
      };
    })).toEqual({ withinViewport: true, noOverflow: true, chartFits: true });
  }
  await popup.getByRole("button", { name: "关闭" }).click();
  await expect(popup).toHaveCount(0);
});
