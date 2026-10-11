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

test("数据库图表：日报值、完整点位、自选保存、刷新恢复与移动端", async ({
  page,
  request,
}) => {
  if (!process.env.WEB_TEST_URL?.includes(":8017"))
    throw new Error("Run database acceptance against isolated port 8017 only");
  const login = await request.post("/api/v1/login/access-token", {
    form: {
      username: env.FIRST_SUPERUSER,
      password: env.FIRST_SUPERUSER_PASSWORD,
    },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token;
  const headers = { Authorization: "Bearer " + token };
  const created = await request.post("/api/v1/projects", {
    headers,
    data: { name: "图表验收工程 " + Date.now() },
  });
  expect(created.ok()).toBeTruthy();
  const project = await created.json(),
    url = `/api/v1/projects/${project.id}`;
  let revision = project.revision;
  const fixtures = [
    [
      "level:建筑物沉降",
      Array.from({ length: 41 }, (_, index) => index + 1).flatMap((i) => [
        {
          时间: "2026-01-01",
          点号: `P${String(i).padStart(2, "0")}`,
          测量值: 10,
        },
        {
          时间: "2026-01-03",
          点号: `P${String(i).padStart(2, "0")}`,
          测量值: 10 - i / 1000,
        },
      ]),
    ],
    [
      "inclinometer:CX01",
      [
        { 深度: "1", "2026-01-01": 0, "2026-01-03": -2 },
        { 深度: "5", "2026-01-01": 0, "2026-01-03": 4 },
        { 深度: "10", "2026-01-01": 0, "2026-01-03": 6 },
      ],
    ],
  ];
  for (const [key, rows] of fixtures) {
    const saved = await request.put(url + "/data", {
      headers,
      data: { revision, measurement_key: key, rows },
    });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    revision = (await saved.json()).revision;
  }
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(
    (value) => sessionStorage.setItem("monitoring_token", value),
    token,
  );
  async function openCharts() {
    await page.getByRole("tab", { name: "数据库图表", exact: true }).click();
  }
  await page.goto(`/projects/${project.id}`);
  await openCharts();
  const card = page
    .locator(".database-chart-card")
    .filter({ has: page.getByRole("heading", { name: /建筑物沉降/ }) });
  await expect(card.getByText("已显示 10 / 41 个点位")).toBeVisible();
  await expect(page.locator(".report-chart canvas")).toHaveCount(2);
  await card.locator("summary").click();
  await expect(card.locator(".chart-value-list b").first()).toHaveText("P41");
  await expect(card.locator(".chart-value-list")).toContainText("-41 mm");
  await page.screenshot({
    path: "../docs/screenshots/database-charts.png",
    fullPage: true,
  });
  await card.getByLabel("点位显示").selectOption("all");
  await expect(card.getByText("已显示 41 / 41 个点位")).toBeVisible();
  await card.getByRole("button", { name: "勾选点位" }).click();
  const modal = page.getByRole("dialog");
  await modal.getByRole("button", { name: "清空", exact: true }).click();
  await modal.getByLabel("P03", { exact: true }).check();
  await modal.getByLabel("P41", { exact: true }).check();
  await modal.getByRole("button", { name: "应用并记住" }).click();
  await expect(modal).not.toBeVisible();
  await expect(card.getByText("已显示 2 / 41 个点位")).toBeVisible();
  await card.getByLabel("图表形式").selectOption("history");
  await expect(card.getByLabel("图表形式")).toHaveValue("history");
  await page.reload();
  await openCharts();
  await expect(card.getByLabel("点位显示")).toHaveValue("custom");
  await expect(card.getByLabel("图表形式")).toHaveValue("history");
  await expect(card.getByText("已显示 2 / 41 个点位")).toBeVisible();
  await page.getByRole("tab", { name: "数据库数据", exact: true }).click();
  await page.getByLabel("数据库日期").selectOption("2026-01-01");
  await expect(page.getByText("共 41 行 · 日期 2026-01-01")).toBeVisible();
  await page.getByLabel("数据内容").selectOption("raw");
  await expect(
    page.getByRole("cell", { name: "2026-01-03", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("数据库日期").selectOption("2026-01-03");
  await expect(
    page.getByRole("cell", { name: "2026-01-01", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("数据内容").selectOption("report");
  await page.getByLabel("筛选数据").fill("P41");
  await expect(
    page.getByRole("cell", { name: "-41", exact: true }).first(),
  ).toBeVisible();
  await page.getByLabel("数据内容").selectOption("raw");
  await expect(
    page.getByRole("cell", { name: "9.959", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "数据库图表", exact: true }).click();
  const depthCard = page
    .locator(".database-chart-card")
    .filter({ has: page.getByRole("heading", { name: /CX01/ }) });
  await depthCard.getByLabel("图表形式").selectOption("history");
  await expect(depthCard.getByLabel("图表形式")).toHaveValue("history");
  await expect(depthCard.locator(".report-chart canvas")).toHaveCount(1);
  await depthCard.screenshot({
    path: "../docs/screenshots/inclinometer-history.png",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card.getByLabel("监测日期")).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/database-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});
