import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import jsQR from "jsqr";
import { PNG } from "pngjs";

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
function decode(buffer: Buffer) {
  const png = PNG.sync.read(buffer);
  return jsQR(new Uint8ClampedArray(png.data), png.width, png.height)?.data;
}

test("工程添加多个账号、成员扫码改图表、移除后收回权限", async ({
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
  const token = (await auth.json()).access_token;
  const headers = { Authorization: "Bearer " + token };
  const email = `member-${Date.now()}@example.com`,
    password = "Membership-test-123!";
  const userResponse = await request.post("/api/v1/users/", {
    headers,
    data: { email, password, full_name: "工程协作用户" },
  });
  expect(userResponse.ok()).toBeTruthy();
  const project = await (
    await request.post("/api/v1/projects", {
      headers,
      data: { name: "共享工程验收 " + Date.now() },
    })
  ).json();
  const measurement = "level:共享沉降";
  const saved = await request.put(`/api/v1/projects/${project.id}/data`, {
    headers,
    data: {
      revision: 1,
      measurement_key: measurement,
      rows: [{ 时间: "2026-01-01", 点号: "A", 测量值: 10 }],
    },
  });
  expect(saved.ok()).toBeTruthy();
  await page.addInitScript(
    (t) => sessionStorage.setItem("monitoring_token", t),
    token,
  );
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("button", { name: "工程成员", exact: true }).click();
  await page.getByLabel("成员账号邮箱").fill(email);
  await page.getByRole("button", { name: "添加成员" }).click();
  await expect(page.getByText(email, { exact: true })).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/project-members.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../docs/screenshots/project-members-mobile.png",
    fullPage: true,
  });

  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const member = await context.newPage();
  await member.goto("/login");
  await member.getByLabel("邮箱", { exact: true }).fill(email);
  await member.getByLabel("密码", { exact: true }).fill(password);
  await member.getByRole("button", { name: "登录", exact: true }).click();
  await member.getByRole("link", { name: new RegExp(project.name) }).click();
  await expect(
    member.getByRole("heading", { name: project.name }),
  ).toBeVisible();
  await expect(
    member.getByRole("button", { name: "工程成员", exact: true }),
  ).toHaveCount(0);
  await member.getByRole("button", { name: "工程设置", exact: true }).click();
  await expect(
    member.getByRole("button", { name: "删除工程", exact: true }),
  ).toHaveCount(0);
  await member.getByRole("button", { name: "关闭", exact: true }).click();
  const destination = `/charts/${project.id}?measurement=${encodeURIComponent(measurement)}`;
  await member.goto(destination);
  await expect(member.locator(".report-chart canvas")).toHaveCount(1);
  const update = member.waitForResponse(
    (r) =>
      r.url().includes("/chart-settings") && r.request().method() === "PUT",
  );
  await member.getByLabel("点位显示").selectOption("all");
  expect((await update).ok()).toBeTruthy();
  await member.reload();
  await expect(member.getByLabel("点位显示")).toHaveValue("all");
  const ownerChart = await request.get(
    `/api/v1/projects/${project.id}/charts?measurement_key=${encodeURIComponent(measurement)}`,
    { headers },
  );
  expect((await ownerChart.json()).settings.mode).toBe("top10");

  page.on("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "移除", exact: true }).click();
  await expect(page.getByText(email, { exact: true })).toHaveCount(0);
  await member.reload();
  await expect(
    member.getByText("工程不存在或没有访问权限", { exact: true }),
  ).toBeVisible();
  await expect(member.locator(".report-chart canvas")).toHaveCount(0);
  await member.goto("/");
  await expect(
    member.getByRole("heading", { name: "我的项目", exact: true }),
  ).toBeVisible();
  await expect(
    member.getByRole("link", { name: new RegExp(project.name) }),
  ).toHaveCount(0);
  await context.close();
});

test("扫码登录错误账号后可切换为工程所属账号并返回原图表", async ({
  page,
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
  const headers = {
    Authorization: "Bearer " + (await auth.json()).access_token,
  };
  const created = await request.post("/api/v1/projects", {
    headers,
    data: { name: "权限恢复验收 " + Date.now() },
  });
  const project = await created.json(),
    measurement = "level:沉降";
  const saved = await request.put(`/api/v1/projects/${project.id}/data`, {
    headers,
    data: {
      revision: project.revision,
      measurement_key: measurement,
      rows: [{ 时间: "2026-01-01", 点号: "A", 测量值: 1 }],
    },
  });
  expect(saved.ok()).toBeTruthy();
  const email = `qr-denied-${Date.now()}@example.com`,
    password = "QR-test-only-123!";
  const user = await request.post("/api/v1/users/", {
    headers,
    data: { email, password, full_name: "扫码权限验收用户" },
  });
  expect(user.ok()).toBeTruthy();
  const destination = `/charts/${project.id}?measurement=${encodeURIComponent(measurement)}`;
  await page.goto(destination);
  await page.getByLabel("邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByText("工程不存在或没有访问权限", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".report-chart")).toHaveCount(0);
  await expect(page.getByText(email, { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "切换账号并返回此图表" }).click();
  await page.getByLabel("邮箱", { exact: true }).fill(env.FIRST_SUPERUSER);
  await page
    .getByLabel("密码", { exact: true })
    .fill(env.FIRST_SUPERUSER_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(
    new URL(destination, process.env.WEB_TEST_URL!).href,
  );
  await expect(page.locator(".report-chart canvas")).toHaveCount(1);
});
test("扫码解码、登录返回测项、手机修改配置并恢复", async ({
  page,
  browser,
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
  const headers = {
    Authorization: "Bearer " + (await login.json()).access_token,
  };
  const created = await request.post("/api/v1/projects", {
    headers,
    data: { name: "扫码验收工程 " + Date.now() },
  });
  const project = await created.json(),
    measurement = "level:地表位移 & A/区";
  const saved = await request.put(`/api/v1/projects/${project.id}/data`, {
    headers,
    data: {
      revision: project.revision,
      measurement_key: measurement,
      rows: [
        { 时间: "2026-01-01", 点号: "D1", 测量值: 10 },
        { 时间: "2026-01-03", 点号: "D1", 测量值: 9.98 },
        { 时间: "2026-01-01", 点号: "D2", 测量值: 10 },
        { 时间: "2026-01-03", 点号: "D2", 测量值: 10.01 },
      ],
    },
  });
  expect(saved.ok()).toBeTruthy();
  await page.addInitScript(
    (value) => sessionStorage.setItem("monitoring_token", value),
    headers.Authorization.slice(7),
  );
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("tab", { name: "数据库图表", exact: true }).click();
  const mini = page.locator(".chart-qr-mini");
  await expect(mini.locator("svg path")).toHaveCount(2);
  const miniUrl = decode(await mini.locator("svg").screenshot());
  expect(miniUrl).toBeTruthy();
  await mini.click();
  const dialog = page.getByRole("dialog");
  const url = await dialog.getByLabel("图表访问地址").inputValue();
  expect(url).toEqual(miniUrl);
  expect(new URL(url).hostname).not.toBe("127.0.0.1");
  expect(new URL(url).searchParams.get("measurement")).toBe(measurement);
  expect(decode(await dialog.locator(".chart-qr-large svg").screenshot())).toBe(
    url,
  );
  const downloaded = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "下载二维码" }).click();
  expect((await downloaded).suggestedFilename()).toMatch(/\.svg$/);
  await page.screenshot({
    path: "../docs/screenshots/chart-qr-dialog.png",
    fullPage: true,
  });

  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const phone = await context.newPage();
  const errors: string[] = [];
  phone.on("pageerror", (e) => errors.push(e.message));
  // Use the actual decoded LAN address from a fresh mobile-size browser.
  await phone.goto(url);
  await expect(phone.getByLabel("邮箱", { exact: true })).toBeVisible();
  await phone.getByLabel("邮箱", { exact: true }).fill(env.FIRST_SUPERUSER);
  await phone
    .getByLabel("密码", { exact: true })
    .fill(env.FIRST_SUPERUSER_PASSWORD);
  await phone.getByRole("button", { name: "登录", exact: true }).click();
  await expect(phone).toHaveURL(url);
  await expect(phone.locator(".report-chart canvas")).toHaveCount(1);
  await phone.getByLabel("图表形式").selectOption("bar");
  await expect(phone.getByLabel("图表形式")).toHaveValue("bar");
  await phone.getByRole("button", { name: "勾选点位" }).click();
  await phone.getByRole("button", { name: "清空", exact: true }).click();
  await phone.getByLabel("D2", { exact: true }).check();
  await phone.getByRole("button", { name: "应用并记住" }).click();
  await expect(phone.getByRole("dialog")).toHaveCount(0);
  await phone.reload();
  await expect(phone.getByLabel("图表形式")).toHaveValue("bar");
  await expect(phone.getByLabel("点位显示")).toHaveValue("custom");
  await expect(phone.getByText("已显示 1 / 2 个点位")).toBeVisible();
  await expect(phone.locator(".report-chart canvas")).toHaveCount(1);
  expect(
    await phone.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  await phone.screenshot({
    path: "../docs/screenshots/chart-qr-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await context.close();
});

test("登录返回地址不能跳转到外部网站", async ({ page }) => {
  if (!process.env.WEB_TEST_URL?.includes(":8017"))
    throw new Error("Use isolated port 8017");
  await page.goto("/login");
  await page.evaluate(() =>
    sessionStorage.setItem("monitoring_login_return", "//example.com/steal"),
  );
  await page.getByLabel("邮箱", { exact: true }).fill(env.FIRST_SUPERUSER);
  await page
    .getByLabel("密码", { exact: true })
    .fill(env.FIRST_SUPERUSER_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "我的项目", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).hostname).toBe("127.0.0.1");
});
