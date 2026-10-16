import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Keep native scrollbar rendering visible during layout acceptance, as in a desktop browser.
test.use({ launchOptions: { ignoreDefaultArgs: ["--hide-scrollbars"] } });

const env = Object.fromEntries(
  fs
    .readFileSync(path.resolve("../.env"), "utf8")
    .split(/\r?\n/)
    .filter((line) => line.includes("=") && !line.startsWith("#"))
    .map((line) => {
      const i = line.indexOf("=");
      let value = line.slice(i + 1);
      try {
        value = JSON.parse(value);
      } catch {}
      return [line.slice(0, i), value];
    }),
);

test("数据库自然高度、完整分页、页面滚动及吸顶宽表", async ({
  page,
  request,
}) => {
  if (!process.env.WEB_TEST_URL?.includes(":8017"))
    throw new Error("Use isolated port 8017");
  const login = await request.post("/api/v1/login/access-token", {
    form: {
      username: env.FIRST_SUPERUSER,
      password: env.FIRST_SUPERUSER_PASSWORD,
    },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token,
    headers = { Authorization: "Bearer " + token };
  const project = await (
    await request.post("/api/v1/projects", {
      headers,
      data: { name: "数据库滚动验收 " + Date.now() },
    })
  ).json();
  let revision = project.revision;
  for (const [measurement_key, rows] of [
    [
      "level:布局验收",
      Array.from({ length: 125 }, (_, i) => {
        const point = `P${String(i + 1).padStart(3, "0")}`;
        return [
          ...(i < 65
            ? [
                {
                  时间: "2026-01-01",
                  点号: point,
                  测量值: "10",
                  备注: "基准期",
                },
              ]
            : []),
          {
            时间: "2026-01-03",
            点号: point,
            测量值: String(10 - i / 1000),
            备注: `第 ${i + 1} 点监测记录，保留完整说明`,
          },
        ];
      }).flat(),
    ],
    [
      "horizontal",
      [{ 时间: "2026-01-03", 点号: "H1", "X 坐标": "10", "Y 坐标": "20" }],
    ],
  ] as const) {
    const saved = await request.put(`/api/v1/projects/${project.id}/data`, {
      headers,
      data: { revision, measurement_key, rows },
    });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    revision = (await saved.json()).revision;
  }
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(
    (t) => sessionStorage.setItem("monitoring_token", t),
    token,
  );
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("tab", { name: "数据库数据", exact: true }).click();
  await page
    .getByLabel("数据库测项", { exact: true })
    .selectOption("level:布局验收");
  const dataRows = page.locator(".database-table table tbody tr");
  await expect(dataRows).toHaveCount(30);
  const pagination = page.getByRole("navigation", { name: "数据库分页" });
  await expect(pagination.getByLabel("每页条数")).toHaveValue("30");
  await page.getByLabel("数据内容", { exact: true }).selectOption("raw");
  const found: string[] = [];
  for (let i = 0; i < 5; i++) {
    await expect(dataRows).toHaveCount(i === 4 ? 5 : 30);
    found.push(
      ...(await dataRows.locator("td").allTextContents()).filter((value) =>
        /^P\d{3}$/.test(value),
      ),
    );
    if (i < 4)
      await pagination
        .getByRole("button", { name: "下一页", exact: true })
        .click();
  }
  expect(new Set(found).size).toBe(125);
  await expect(
    pagination.getByRole("button", { name: "下一页", exact: true }),
  ).toBeDisabled();
  await pagination.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(dataRows).toHaveCount(30);
  await expect(dataRows.first()).toContainText("P091");
  for (const count of [10, 20, 40, 50, 30]) {
    await pagination.getByLabel("每页条数").selectOption(String(count));
    await expect(dataRows).toHaveCount(count);
    await expect(pagination.getByText(/第 1 \/ /)).toBeVisible();
  }
  await pagination.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "../docs/screenshots/database-data-pagination.png",
  });
  await pagination.getByRole("button", { name: "下一页", exact: true }).click();
  await page.getByLabel("筛选数据", { exact: true }).fill("P125");
  await expect(dataRows).toHaveCount(1);
  await expect(
    pagination.getByText("第 1 / 1 页", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("筛选数据", { exact: true }).fill("不存在的测点");
  await expect(dataRows).toHaveCount(0);
  await expect(
    pagination.getByRole("button", { name: "上一页", exact: true }),
  ).toBeDisabled();
  await expect(
    pagination.getByRole("button", { name: "下一页", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("筛选数据", { exact: true }).fill("");
  await pagination.getByLabel("每页条数").selectOption("all");
  await expect(dataRows).toHaveCount(125);
  await page
    .getByLabel("数据库日期", { exact: true })
    .selectOption("2026-01-01");
  await expect(dataRows).toHaveCount(65);
  await page
    .getByLabel("数据库测项", { exact: true })
    .selectOption("horizontal");
  await expect(dataRows).toHaveCount(1);
  await page
    .getByLabel("数据库测项", { exact: true })
    .selectOption("level:布局验收");
  await page
    .getByLabel("数据库日期", { exact: true })
    .selectOption("2026-01-03");
  await page.getByLabel("数据内容", { exact: true }).selectOption("raw");
  await expect(dataRows).toHaveCount(125);
  await page
    .getByRole("columnheader", { name: "点号", exact: true })
    .getByRole("button")
    .click();
  await page
    .getByRole("columnheader", { name: /点号/ })
    .getByRole("button")
    .click();
  await expect(dataRows.first()).toContainText("P125");
  await page.getByLabel("数据内容", { exact: true }).selectOption("report");
  await expect(dataRows).toHaveCount(125);
  const reportTable = page.locator(".database-read-table--report");
  await expect(reportTable).toBeVisible();
  await expect(
    page.getByRole("region", { name: "数据库表格横向滚动" }),
  ).toBeHidden();
  await expect(
    reportTable
      .locator(".database-column-unit")
      .filter({ hasText: "（m）" })
      .first(),
  ).toBeVisible();
  expect(
    await reportTable.evaluate((table) => {
      const style = getComputedStyle(table);
      const viewport = table.closest(".database-table-surface")!;
      return {
        layout: style.tableLayout,
        widthFits:
          table.getBoundingClientRect().width <= viewport.clientWidth + 1,
        headerWhiteSpace: getComputedStyle(table.querySelector("th")!)
          .whiteSpace,
      };
    }),
  ).toMatchObject({
    layout: "fixed",
    widthFits: true,
    headerWhiteSpace: "normal",
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../docs/screenshots/database-data-compact.png",
    fullPage: false,
  });

  for (const width of [1440, 1024, 760, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const surface = page.locator(".database-table-surface");
    await expect(surface).toBeVisible();
    expect(
      await surface.evaluate((el) =>
        Math.abs(
          el.clientHeight -
            el.querySelector("table")!.getBoundingClientRect().height,
        ),
      ),
    ).toBeLessThanOrEqual(1);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
    expect(
      await page.locator(".database-table").evaluate(
        (element) =>
          Array.from(element.querySelectorAll("*")).filter((node) => {
            const el = node as HTMLElement,
              style = getComputedStyle(el);
            return (
              ["auto", "scroll"].includes(style.overflowY) &&
              el.scrollHeight > el.clientHeight + 1
            );
          }).length,
      ),
    ).toBe(0);
    await surface.evaluate((el) =>
      window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top + 300),
    );
    const header = page.locator(".database-read-table th").first();
    await expect
      .poll(() =>
        header.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
      )
      .toBeGreaterThanOrEqual(57);
    expect(await header.evaluate((el) => getComputedStyle(el).position)).toBe(
      "sticky",
    );
    const navBottom = await page
      .locator(".topbar")
      .evaluate((el) => el.getBoundingClientRect().bottom);
    const headerTop = await header.evaluate(
      (el) => el.getBoundingClientRect().top,
    );
    expect(headerTop).toBeGreaterThanOrEqual(navBottom - 1);
    expect(headerTop).toBeLessThan(navBottom + 25);
    await page.mouse.move(width > 720 ? 400 : 180, 360);
    let before = await page.evaluate(() => window.scrollY);
    await page.mouse.wheel(0, 240);
    await expect
      .poll(() => page.evaluate(() => window.scrollY))
      .toBeGreaterThan(before + 100);
    before = await page.evaluate(() => window.scrollY);
    await page.mouse.wheel(80, 240);
    await expect
      .poll(() => page.evaluate(() => window.scrollY))
      .toBeGreaterThan(before + 100);
    await surface.evaluate((el) =>
      (el as HTMLElement).focus({ preventScroll: true }),
    );
    before = await page.evaluate(() => window.scrollY);
    await page.keyboard.press("PageDown");
    await expect
      .poll(() => page.evaluate(() => window.scrollY))
      .toBeGreaterThan(before + 100);
    const horizontal = page.getByRole("region", { name: "数据库表格横向滚动" });
    if (await horizontal.isVisible()) {
      await horizontal.evaluate((el) => (el.scrollLeft = 0));
      await expect
        .poll(() =>
          page
            .locator(".database-read-table")
            .evaluate((el) => el.getBoundingClientRect().left),
        )
        .toBeGreaterThanOrEqual(0);
      const initialLeft = await page
        .locator(".database-read-table")
        .evaluate((el) => el.getBoundingClientRect().left);
      await horizontal.evaluate((el) => (el.scrollLeft = el.scrollWidth));
      await expect
        .poll(() =>
          page
            .locator(".database-read-table")
            .evaluate((el) => el.getBoundingClientRect().left),
        )
        .toBeLessThan(initialLeft - 1);
    }
    if (width === 1024 || width === 390)
      await page.screenshot({
        path: `../docs/screenshots/database-data-sticky-${width}.png`,
      });
  }
  expect(errors).toEqual([]);
});
