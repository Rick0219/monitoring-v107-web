import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const env = Object.fromEntries(
  fs
    .readFileSync(path.resolve("../.env"), "utf8")
    .split(/\r?\n/)
    .filter((line) => line.includes("=") && !line.startsWith("#"))
    .map((line) => {
      const index = line.indexOf("=");
      let value: string | unknown = line.slice(index + 1);
      try {
        value = JSON.parse(value);
      } catch {}
      return [line.slice(0, index), value];
    }),
);

test("水准原始数据导入入口显示三步向导", async ({ page, request }) => {
  test.skip(!process.env.WEB_TEST_URL?.includes(":8017"), "Use isolated port 8017");
  const login = await request.post("/api/v1/login/access-token", {
    form: {
      username: process.env.WEB_TEST_USER || env.FIRST_SUPERUSER || "admin@example.com",
      password: process.env.WEB_TEST_PASSWORD || env.FIRST_SUPERUSER_PASSWORD || "HoNTsbSUySBr4TnChYdK",
    },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token;
  const headers = { Authorization: "Bearer " + token };
  const project = await (
    await request.post("/api/v1/projects", {
      headers,
      data: { name: "水准导入入口 " + Date.now() },
    })
  ).json();
  await page.addInitScript(
    (value) => sessionStorage.setItem("monitoring_token", value),
    token,
  );
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("button", { name: "水准", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "原始数据导入", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "原始数据导入", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "原始数据导入" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "选择原始文件" })).toBeVisible();

  const files = [
    ["BM1", "Z2,-16.8744\n"],
    [
      "DAT",
      "For M5|Adr 196|KD1       Z2                123|                      |                      |Z       -16.87440 m   |\nFor M5|Adr 197|KD1       Z2              1 123|Rb        1.45965 m   |HD         11.182 m   |                      |\nFor M5|Adr 198|KD1       Z1              1 123|Rf        1.38073 m   |HD         12.485 m   |                      |\nFor M5|Adr 199|KD1       Z1                123|                      |                      |Z       -16.79551 m   |",
    ],
    ["hdf", "测站 后视 前视 测站高差 累计测距\n1 Z2 Z1 1.45965 23.666 0.07889\n2 Z1 Z2 1.38060 23.839 -0.07800\n"],
    ["in1", "Z2,-16.8744\nZ2,Z1,0.07889,0.024,1\nZ1,Z2,-0.07800,0.024,1\n"],
    ["gco", "闭合差： 0.89(MM)\n闭合路线长度： 0.0475(KM)\n以环线长度计算国家二等限差： 4.0000(MM)\n每公里水准测量全中误差： 0.15(MM/KM)\n"],
    ["ou1", "1 Z2 -16.8744\n2 Z1 -16.7955\n3 Z2 -16.8744\n"],
    ["our", "1,Z2,-16.87440,0.00,2026年10月12日\n2,Z1,-16.79550,0.03,2026年10月12日\n"],
  ] as const;
  const uploaders = page.getByRole("dialog").locator('input[type="file"]');
  for (const [index, [extension, content]] of files.entries()) {
    await uploaders.nth(index).setInputFiles({
      name: `fixture.${extension}`,
      mimeType: "text/plain",
      buffer: Buffer.from(content, "utf8"),
    });
  }
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(page.getByRole("heading", { name: "平差设置" })).toBeVisible();
  await page.getByLabel("观测日期", { exact: true }).fill("2026-10-12");
  await page.getByRole("button", { name: /预览平差结果/ }).click();
  await expect(page.getByRole("heading", { name: "点号映射与写入" })).toBeVisible();
  await expect(page.getByText("质量检查通过", { exact: true })).toBeVisible();
});

test("只上传 DAT 时跳过平差直接进入点号映射", async ({ page, request }) => {
  test.skip(!process.env.WEB_TEST_URL?.includes(":8017"), "Use isolated port 8017");
  const login = await request.post("/api/v1/login/access-token", {
    form: {
      username: process.env.WEB_TEST_USER || env.FIRST_SUPERUSER || "admin@example.com",
      password: process.env.WEB_TEST_PASSWORD || env.FIRST_SUPERUSER_PASSWORD || "HoNTsbSUySBr4TnChYdK",
    },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token;
  const project = await (await request.post("/api/v1/projects", {
    headers: { Authorization: "Bearer " + token }, data: { name: "DAT 直接映射 " + Date.now() },
  })).json();
  await page.addInitScript((value) => sessionStorage.setItem("monitoring_token", value), token);
  await page.goto(`/projects/${project.id}`);
  await page.getByRole("button", { name: "水准", exact: true }).click();
  await page.getByRole("button", { name: "原始数据导入", exact: true }).click();
  const dat = [
    "For M5|Adr 1|TO Start-Line aBFFB 123|",
    "For M5|Adr 2|KD1 P1 123| | |Z 10.00000 m |",
    "For M5|Adr 3|KD1 P1 1 123|Rb 1.50000 m |HD 10.000 m | |",
    "For M5|Adr 4|KD1 P2 1 123|Rf 1.40000 m |HD 20.000 m | |",
    "For M5|Adr 5|KD1 P2 123| | |Z 10.10000 m |",
  ].join("\n");
  await page.getByRole("dialog").locator('input[type="file"]').first().setInputFiles({
    name: "direct.DAT", mimeType: "text/plain", buffer: Buffer.from(dat, "utf8"),
  });
  await page.getByRole("button", { name: "下一步", exact: true }).click();
  await expect(page.getByRole("heading", { name: "点号映射与写入" })).toBeVisible();
  await expect(page.getByText("未进行平差", { exact: true })).toBeVisible();
  await expect(page.getByText(/未上传控制点文件/)).toBeVisible();
});
