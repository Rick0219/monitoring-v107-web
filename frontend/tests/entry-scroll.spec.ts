import {
  test,
  expect,
  type Page,
  type APIRequestContext,
  type Locator,
} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

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

async function openFixture(page: Page, request: APIRequestContext) {
  if (!process.env.WEB_TEST_URL?.includes(":8017"))
    throw new Error("Use isolated port 8017");
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
    data: { name: "多行滚动验收 " + Date.now() },
  });
  expect(created.ok()).toBeTruthy();
  const project = await created.json();
  const saved = await request.put(`/api/v1/projects/${project.id}/data`, {
    headers,
    data: {
      revision: project.revision,
      measurement_key: "level:建筑物位移",
      rows: Array.from({ length: 125 }, (_, i) => ({
        时间: "2026-01-03",
        点号: `P${i + 1}`,
        测量值: "10",
        备注: "多行数据",
      })),
    },
  });
  expect(saved.ok()).toBeTruthy();
  await page.addInitScript(
    (t) => sessionStorage.setItem("monitoring_token", t),
    token,
  );
  await page.goto(`/projects/${project.id}`);
}
async function expectNoInnerVerticalScroll(root: Locator) {
  const scrollable = await root.evaluate((element) =>
    [
      ...(element.matches(".entry-grid") ? [element] : []),
      ...element.querySelectorAll("*"),
    ]
      .filter((node) => {
        const el = node as HTMLElement;
        return (
          ["auto", "scroll"].includes(getComputedStyle(el).overflowY) &&
          el.scrollHeight > el.clientHeight + 1
        );
      })
      .map((el) => el.className),
  );
  expect(scrollable).toEqual([]);
}

test("单期录入多行自然展开，滚轮和 PageDown 滚动页面，翻页保留草稿", async ({
  page,
  request,
}) => {
  await openFixture(page, request);
  await page.getByRole("button", { name: "水准", exact: true }).click();
  await page.getByLabel("监测日期", { exact: true }).fill("2026-01-03");
  const grid = page.locator(".entry-grid");
  await expect(grid.locator("tbody tr")).toHaveCount(100);
  await page.getByLabel("新增行数").fill("5");
  await page.getByRole("button", { name: "添加数据", exact: true }).click();
  await expect(page.locator(".database-pagination")).toContainText("共 130 行");
  await expectNoInnerVerticalScroll(grid);
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const surface = grid.locator(".database-table-surface");
    await expectNoInnerVerticalScroll(grid);
    expect(
      await surface.evaluate((el) =>
        Math.abs(
          el.clientHeight -
            el.querySelector("table")!.getBoundingClientRect().height,
        ),
      ),
    ).toBeLessThanOrEqual(1);
    await surface.evaluate((el) =>
      window.scrollTo(0, scrollY + el.getBoundingClientRect().top + 300),
    );
    await page.mouse.move(width > 720 ? 430 : 180, 350);
    let before = await page.evaluate(() => scrollY);
    await page.mouse.wheel(50, 240);
    await expect
      .poll(() => page.evaluate(() => scrollY))
      .toBeGreaterThan(before + 100);
    await surface.evaluate((el) =>
      (el as HTMLElement).focus({ preventScroll: true }),
    );
    before = await page.evaluate(() => scrollY);
    await page.keyboard.press("PageDown");
    await expect
      .poll(() => page.evaluate(() => scrollY))
      .toBeGreaterThan(before + 100);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
    if (width === 1024 || width === 390)
      await page.screenshot({
        path: `../docs/screenshots/entry-page-scroll-${width}.png`,
      });
  }
  await page.getByLabel("第100行 备注", { exact: true }).fill("翻页后保留");
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(grid.locator("tbody tr")).toHaveCount(30);
  await expect(
    page.getByLabel("第130行 测量值", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.getByLabel("第100行 备注", { exact: true })).toHaveValue(
    "翻页后保留",
  );
});

test("编辑当日数据仅弹窗纵向滚动，背景锁定，分页编辑保存不变", async ({
  page,
  request,
}) => {
  await openFixture(page, request);
  await page.getByRole("tab", { name: "数据库数据", exact: true }).click();
  await page.getByRole("button", { name: "编辑当日数据", exact: true }).click();
  const modal = page.getByRole("dialog");
  await expect(modal.locator("tbody tr")).toHaveCount(50);
  await expectNoInnerVerticalScroll(modal);
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expectNoInnerVerticalScroll(modal);
    await expect
      .poll(() =>
        page.evaluate(
          () => getComputedStyle(document.documentElement).overflowY,
        ),
      )
      .toBe("hidden");
    const backgroundY = await page.evaluate(() => scrollY);
    await modal.evaluate((el) => (el.scrollTop = 200));
    const box = (await modal.boundingBox())!;
    const headerTop = await modal
      .locator("th")
      .first()
      .evaluate((el) => el.getBoundingClientRect().top);
    expect(headerTop).toBeGreaterThanOrEqual(box.y);
    expect(headerTop).toBeLessThanOrEqual(box.y + 21);
    await page.mouse.move(box.x + box.width / 2, box.y + 300);
    let before = await modal.evaluate((el) => el.scrollTop);
    await page.mouse.wheel(50, 240);
    await expect
      .poll(() => modal.evaluate((el) => el.scrollTop))
      .toBeGreaterThan(before + 100);
    const surface = modal.locator(".database-table-surface");
    await surface.evaluate((el) =>
      (el as HTMLElement).focus({ preventScroll: true }),
    );
    before = await modal.evaluate((el) => el.scrollTop);
    await page.keyboard.press("PageDown");
    await expect
      .poll(() => modal.evaluate((el) => el.scrollTop))
      .toBeGreaterThan(before + 100);
    expect(await page.evaluate(() => scrollY)).toBe(backgroundY);
    expect(
      await modal.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBeTruthy();
    if (width === 1024 || width === 390)
      await page.screenshot({
        path: `../docs/screenshots/database-editor-scroll-${width}.png`,
      });
  }
  await modal.getByRole("button", { name: "下一页", exact: true }).click();
  await modal.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(modal.locator("tbody tr")).toHaveCount(25);
  await modal.getByLabel("第125行 测量值", { exact: true }).fill("9.99");
  await modal
    .getByRole("button", { name: "保存当日数据", exact: true })
    .click();
  await expect(modal).not.toBeVisible();
  expect(
    await page.evaluate(
      () => getComputedStyle(document.documentElement).overflowY,
    ),
  ).not.toBe("hidden");
  await page.getByLabel("数据内容").selectOption("raw");
  await page.getByLabel("筛选数据").fill("P125");
  await expect(
    page.getByRole("cell", { name: "9.99", exact: true }),
  ).toBeVisible();
});
