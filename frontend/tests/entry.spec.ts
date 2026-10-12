import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

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

async function adminLogin(request: any) {
  if (!process.env.WEB_TEST_URL?.includes(":8017"))
    throw new Error("Use isolated port 8017");
  const result = await request.post("/api/v1/login/access-token", {
    form: {
      username: env.FIRST_SUPERUSER,
      password: env.FIRST_SUPERUSER_PASSWORD,
    },
  });
  expect(result.ok()).toBeTruthy();
  const token = (await result.json()).access_token;
  return { token, headers: { Authorization: "Bearer " + token } };
}
async function newMeasurement(page: Page, type: string) {
  const labels: Record<string, string> = {
    level: "水准",
    tilt: "倾斜",
    horizontal: "水平位移",
    axial: "支撑轴力",
    water: "水位",
    inclinometer: "深层水平位移",
  };
  const back = page.getByRole("button", { name: "更换监测类型", exact: true });
  if (await back.isVisible()) await back.click();
  await page.getByRole("button", { name: labels[type], exact: true }).click();
  await expect(page.getByLabel("监测日期", { exact: true })).toBeVisible();
}
async function savePeriod(page: Page) {
  await page.getByRole("button", { name: "保存数据", exact: true }).click();
  await expect(
    page.getByText("数据已保存到当前工程", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "保存数据", exact: true }),
  ).toBeDisabled();
}

test("桌面一致录入：轴力、水位、倾斜、测斜、水平位移及导入预览", async ({
  page,
  request,
}) => {
  const admin = await adminLogin(request);
  const p = await (
    await request.post("/api/v1/projects", {
      headers: admin.headers,
      data: { name: "分类型录入验收 " + Date.now() },
    })
  ).json();
  const url = `/api/v1/projects/${p.id}`;
  await request.put(url + "/data", {
    headers: admin.headers,
    data: {
      revision: 1,
      measurement_key: "level:建筑物位移",
      rows: [
        { 时间: "2026-01-01", 点号: "A", 测量值: 10 },
        { 时间: "2026-01-01", 点号: "B", 测量值: 20 },
        { 时间: "2026-01-03", 点号: "A", 测量值: 9.99 },
        { 时间: "2026-01-03", 点号: "B", 测量值: 19.995 },
      ],
    },
  });
  await page.addInitScript(
    (token) => sessionStorage.setItem("monitoring_token", token),
    admin.token,
  );
  await page.goto(`/projects/${p.id}`);
  await newMeasurement(page, "axial");
  await expect(page.getByLabel("当前测项").locator("option")).toHaveText([
    "支撑轴力 · 第一道支撑",
  ]);
  await page.getByLabel("监测日期", { exact: true }).fill("2026-01-03");
  await page.getByRole("button", { name: "轴力参数", exact: true }).click();
  await page.getByRole("button", { name: "新增编号", exact: true }).click();
  for (const [label, value] of [
    ["点号", "Z1"],
    ["编号", "1"],
    ["标定系数 K（kN/Hz²）", ".001"],
    ["初始频率 f0（Hz）", "1000"],
    ["轴力转换系数 C（无量纲）", "2"],
  ]) {
    await page.getByLabel("参数第1行 " + label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "保存参数", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "新增点位", exact: true }).click();
  await page.getByRole("button", { name: "加载全部编号", exact: true }).click();
  await page.getByLabel("第1行 频率", { exact: true }).fill("1100");
  await expect(
    page.getByLabel("第1行 轴力（kN）", { exact: true }),
  ).toHaveValue("420");
  await expect(
    page.getByLabel("第1行 轴力（kN）", { exact: true }),
  ).toHaveAttribute("readonly", "");
  await savePeriod(page);
  await page.screenshot({
    path: "../docs/screenshots/entry-axial.png",
    fullPage: true,
  });

  await newMeasurement(page, "water");
  await page.getByRole("button", { name: "水位参数", exact: true }).click();
  await page.getByRole("button", { name: "新增参数行", exact: true }).click();
  await page.getByLabel("参数第1行 点位", { exact: true }).fill("W1");
  await page.getByLabel("参数第1行 管口高程（m）", { exact: true }).fill("10");
  await page.getByRole("button", { name: "保存参数", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByLabel("第1行 管口高程（m）", { exact: true }),
  ).toHaveValue("10");
  await page.getByLabel("第1行 水位读数（m）", { exact: true }).fill("2");
  await savePeriod(page);

  await newMeasurement(page, "tilt");
  await page.getByRole("button", { name: "测点参数", exact: true }).click();
  await page.getByRole("button", { name: "新增参数行", exact: true }).click();
  await page.getByLabel("参数第1行 点号1", { exact: true }).selectOption("A");
  await page.getByLabel("参数第1行 点号2", { exact: true }).selectOption("B");
  await page.getByLabel("参数第1行 两点距离L（m）", { exact: true }).fill("5");
  await page.getByRole("button", { name: "保存参数", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByLabel("第1行 倾斜度（‰）", { exact: true }),
  ).toHaveValue("1");
  await expect(
    page.getByLabel("第1行 倾斜度（‰）", { exact: true }),
  ).toHaveAttribute("readonly", "");

  await newMeasurement(page, "inclinometer");
  await page.getByRole("button", { name: "孔号参数", exact: true }).click();
  await page.getByLabel("参数第1行 深度", { exact: true }).fill("2");
  await page.getByRole("button", { name: "保存参数", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("第4行 深度", { exact: true })).toHaveValue("2");
  await page.getByLabel("第1行 测值", { exact: true }).fill("1");
  await savePeriod(page);
  await page.getByLabel("观测批次", { exact: true }).selectOption("（加密）");
  await page.getByLabel("第1行 测值", { exact: true }).fill("2");
  await savePeriod(page);
  let saved = await (
    await request.get(url + "/data", { headers: admin.headers })
  ).json();
  expect(saved.measurements["inclinometer:CX01"][0]["2026-01-03"]).toBe("1");
  expect(saved.measurements["inclinometer:CX01"][0]["2026-01-03（加密）"]).toBe(
    "2",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/screenshots/entry-inclinometer-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });

  await newMeasurement(page, "horizontal");
  const before = (
    await (await request.get(url, { headers: admin.headers })).json()
  ).revision;
  await page
    .locator('input[type=file][accept=".xlsx,.xlsm,.csv"]')
    .setInputFiles({
      name: "coordinates.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("点号,X 坐标,Y 坐标\nH1,10,20\n"),
    });
  await expect(page.getByRole("dialog", { name: "导入预览" })).toBeVisible();
  expect(
    (await (await request.get(url, { headers: admin.headers })).json())
      .revision,
  ).toBe(before);
  await page.getByRole("button", { name: "应用到录入表", exact: true }).click();
  await expect(page.getByLabel("第1行 X 坐标", { exact: true })).toHaveValue(
    "10",
  );
  await savePeriod(page);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 Excel 模板" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.xlsx$/);
});

test("先选监测类型：类型隔离、缺少水准源提示和草稿切换保护", async ({
  page,
  request,
}) => {
  const admin = await adminLogin(request);
  const project = await (
    await request.post("/api/v1/projects", {
      headers: admin.headers,
      data: { name: "类型入口验收 " + Date.now() },
    })
  ).json();
  await page.addInitScript(
    (token) => sessionStorage.setItem("monitoring_token", token),
    admin.token,
  );
  const entryReads: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "GET" && r.url().includes("/entry?"))
      entryReads.push(r.url());
  });
  await page.goto(`/projects/${project.id}`);
  await expect(
    page.getByRole("heading", { name: "选择单期监测类型" }),
  ).toBeVisible();
  await expect(page.locator(".entry-type-card")).toHaveCount(6);
  await expect
    .poll(() =>
      page
        .locator(".entry-type-card img")
        .evaluateAll((images) =>
          images.every(
            (image) =>
              (image as HTMLImageElement).complete &&
              (image as HTMLImageElement).naturalWidth > 0,
          ),
        ),
    )
    .toBe(true);
  await expect(page.getByLabel("监测日期", { exact: true })).toHaveCount(0);
  expect(entryReads).toHaveLength(0);
  await page.screenshot({
    path: "../docs/screenshots/entry-types.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/screenshots/entry-types-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "倾斜", exact: true }).click();
  await expect(
    page.getByText("请先录入水准数据，再配置倾斜测点参数。", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "去录入水准数据", exact: true })
    .click();
  await page.getByRole("button", { name: "新增一行", exact: true }).click();
  await page.getByLabel("第1行 点号", { exact: true }).fill("KEEP-ME");
  await page.getByLabel("第1行 测量值", { exact: true }).fill("10");
  // Opening or cancelling the naming dialog must not discard current entry rows.
  await page.getByRole("button", { name: "新建测项", exact: true }).click();
  const createDialog = page.getByRole("dialog", {
    name: "新建测项",
    exact: true,
  });
  await expect(createDialog).toBeVisible();
  await createDialog.getByLabel("测项名称", { exact: true }).fill("新地表测项");
  await createDialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByLabel("第1行 点号", { exact: true })).toHaveValue(
    "KEEP-ME",
  );
  await expect(page.getByLabel("测项名称", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "新建测项", exact: true }).click();
  await createDialog.getByLabel("测项名称", { exact: true }).fill("新地表测项");
  page.once("dialog", (d) => d.dismiss());
  await createDialog
    .getByRole("button", { name: "确认新建", exact: true })
    .click();
  await expect(createDialog).toBeVisible();
  await expect(page.getByLabel("第1行 点号", { exact: true })).toHaveValue(
    "KEEP-ME",
  );
  await createDialog.getByRole("button", { name: "取消", exact: true }).click();
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "更换监测类型", exact: true }).click();
  await expect(page.getByLabel("第1行 点号", { exact: true })).toHaveValue(
    "KEEP-ME",
  );
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "更换监测类型", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "选择单期监测类型" }),
  ).toBeVisible();
  expect(
    (
      await (
        await request.get(`/api/v1/projects/${project.id}`, {
          headers: admin.headers,
        })
      ).json()
    ).revision,
  ).toBe(1);
  await newMeasurement(page, "axial");
  await expect(
    page.getByRole("button", { name: "轴力参数", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "水位参数", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("当前测项").locator("option")).toHaveText([
    "支撑轴力 · 第一道支撑",
  ]);
  await page.getByRole("button", { name: "新建测项", exact: true }).click();
  await createDialog.getByLabel("测项名称", { exact: true }).fill("   ");
  await createDialog
    .getByRole("button", { name: "确认新建", exact: true })
    .click();
  await expect(
    createDialog.getByText("请填写测项名称", { exact: true }),
  ).toBeVisible();
  await createDialog.getByLabel("测项名称", { exact: true }).fill("第二道支撑");
  await page.screenshot({
    path: "../docs/screenshots/entry-new-measurement.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/screenshots/entry-new-measurement-mobile.png",
    fullPage: true,
  });
  await createDialog
    .getByRole("button", { name: "确认新建", exact: true })
    .click();
  await expect(createDialog).toHaveCount(0);
  await expect(page.getByLabel("当前测项")).toHaveValue("axial:第二道支撑");
  await expect(
    page.getByRole("button", { name: "轴力参数", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await newMeasurement(page, "water");
  await expect(
    page.getByRole("button", { name: "水位参数", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "新建测项", exact: true }),
  ).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "选择单期监测类型" }),
  ).toBeVisible();
});

test("整行和测值粘贴：空表扩行、空值不移位、自动列保护与保存", async ({
  page,
  context,
  request,
}) => {
  const admin = await adminLogin(request);
  const project = await (
    await request.post("/api/v1/projects", {
      headers: admin.headers,
      data: { name: "批量粘贴验收 " + Date.now() },
    })
  ).json();
  await page.addInitScript(
    (token) => sessionStorage.setItem("monitoring_token", token),
    admin.token,
  );
  await page.goto(`/projects/${project.id}`);
  await newMeasurement(page, "level");
  await page.getByLabel("监测日期", { exact: true }).fill("2026-01-03");
  await page.getByRole("button", { name: "批量粘贴", exact: true }).click();
  await page
    .getByLabel("待粘贴数据", { exact: true })
    .fill("点号\t测量值\t备注\nP1\t10\t正常\nP2\t\t缺测\nP3\t12\t正常\n");
  await page.screenshot({
    path: "../docs/screenshots/entry-bulk-paste.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/screenshots/entry-bulk-paste-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "应用粘贴", exact: true }).click();
  await expect(page.getByLabel("第3行 测量值", { exact: true })).toHaveValue(
    "12",
  );
  await expect(page.getByLabel("第2行 测量值", { exact: true })).toHaveValue(
    "",
  );
  expect(
    (
      await (
        await request.get(`/api/v1/projects/${project.id}`, {
          headers: admin.headers,
        })
      ).json()
    ).revision,
  ).toBe(1);

  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  async function paste(label: string, value: string) {
    await page.evaluate((text) => navigator.clipboard.writeText(text), value);
    await page.getByLabel(label, { exact: true }).click();
    await page.keyboard.press("Control+V");
  }
  await paste("第1行 测量值", "20\n\n22\n");
  await expect(page.getByLabel("第3行 测量值", { exact: true })).toHaveValue(
    "22",
  );
  await expect(page.getByLabel("第2行 测量值", { exact: true })).toHaveValue(
    "",
  );
  await expect(page.getByLabel("第3行 点号", { exact: true })).toHaveValue(
    "P3",
  );
  // Whole rows may include readonly sequence/date values; current period must win.
  await paste(
    "第1行 序号",
    "序号\t时间\t点号\t测量值\t备注\n99\t2000-01-01\tP1\t30\t复测\n98\t2000-01-01\tP2\t31\t复测\n97\t2000-01-01\tP3\t32\t复测\n96\t2000-01-01\tP4\t33\t复测",
  );
  await expect(page.getByLabel("第4行 序号", { exact: true })).toHaveValue("4");
  await expect(page.getByLabel("第4行 时间", { exact: true })).toHaveValue(
    "2026-01-03",
  );
  await expect(page.getByLabel("第4行 测量值", { exact: true })).toHaveValue(
    "33",
  );
  await page.getByLabel("筛选数据", { exact: true }).fill("P1");
  await paste("第1行 测量值", "90\n91");
  await expect(
    page.getByText("请先清除筛选，再批量粘贴，避免覆盖隐藏行。", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByLabel("筛选数据", { exact: true }).fill("");
  await expect(page.getByLabel("第2行 测量值", { exact: true })).toHaveValue(
    "31",
  );
  await savePeriod(page);
  const saved = await (
    await request.get(`/api/v1/projects/${project.id}/data`, {
      headers: admin.headers,
    })
  ).json();
  expect(
    saved.measurements["level:建筑物位移"].map((r: any) => Number(r["测量值"])),
  ).toEqual([30, 31, 32, 33]);
  await page.screenshot({
    path: "../docs/screenshots/entry-pasted-rows.png",
    fullPage: true,
  });
});

test("工程删除：创建人和管理员可操作，普通成员隐藏，取消不删除", async ({
  page,
  browser,
  request,
}) => {
  const admin = await adminLogin(request);
  const password = "Delete-test-123!";
  const email = `delete-owner-${Date.now()}@example.com`,
    memberEmail = `delete-member-${Date.now()}@example.com`;
  const owner = await (
    await request.post("/api/v1/users/", {
      headers: admin.headers,
      data: { email, password },
    })
  ).json();
  await request.post("/api/v1/users/", {
    headers: admin.headers,
    data: { email: memberEmail, password },
  });
  async function login(username: string) {
    return (
      await (
        await request.post("/api/v1/login/access-token", {
          form: { username, password },
        })
      ).json()
    ).access_token;
  }
  const token = await login(email),
    headers = { Authorization: "Bearer " + token };
  const p = await (
    await request.post("/api/v1/projects", {
      headers,
      data: { name: "删除验收 " + Date.now() },
    })
  ).json();
  await request.post(`/api/v1/projects/${p.id}/members`, {
    headers,
    data: { email: memberEmail },
  });
  await request.patch("/api/v1/users/" + owner.id, {
    headers: admin.headers,
    data: { permissions: [] },
  });
  await page.addInitScript(
    (t) => sessionStorage.setItem("monitoring_token", t),
    token,
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "删除工程 " + p.name, exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "确认删除工程" }),
  ).toContainText(p.name);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  expect(
    (await request.get(`/api/v1/projects/${p.id}`, { headers })).ok(),
  ).toBeTruthy();
  const context = await browser.newContext();
  const member = await context.newPage();
  await member.addInitScript(
    (t) => sessionStorage.setItem("monitoring_token", t),
    await login(memberEmail),
  );
  await member.goto(`/projects/${p.id}`);
  await expect(
    member.getByRole("heading", { name: p.name, exact: true }),
  ).toBeVisible();
  await expect(member.getByRole("button", { name: /删除工程/ })).toHaveCount(0);
  await context.close();
  await page.goto(`/projects/${p.id}`);
  await page
    .getByRole("button", { name: "删除工程 " + p.name, exact: true })
    .click();
  await page.screenshot({
    path: "../docs/screenshots/delete-project-confirmation.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "我的项目", exact: true }),
  ).toBeVisible();
  expect(
    (
      await request.get(`/api/v1/projects/${p.id}`, { headers: admin.headers })
    ).status(),
  ).toBe(404);
});
