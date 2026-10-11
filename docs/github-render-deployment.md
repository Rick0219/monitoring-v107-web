# GitHub + Render 部署

当前网页是 FastAPI 全栈应用。GitHub 用来保存代码并触发部署，Render 运行 FastAPI、PostgreSQL 和文件存储；只开启 GitHub Pages 会缺少登录、数据库、权限、AI 问答和文件上传接口。

## 发布前检查

1. 在 GitHub 创建私有仓库 `monitoring-v107-web`，不要上传 `.env`、`data/`、`backend/app/frontend/`、首次登录密码或任何 API Key。
2. 把本目录内容推送到该仓库的默认分支。
3. 在 Render 选择 **New → Blueprint**，连接该 GitHub 仓库并选择根目录的 `render.yaml`。
4. 首次创建时填写 `FIRST_SUPERUSER` 和 `FIRST_SUPERUSER_PASSWORD`。密码至少 12 位，保存到 Render 的环境变量，不写入 GitHub。
5. Render 会创建 PostgreSQL 数据库、带持久磁盘的 Web 服务，并使用 `Dockerfile` 构建前端和后端。健康检查地址为 `/api/v1/health`。

部署后先使用 Render 分配的网址，例如：

```text
https://monitoring-v107-web.onrender.com
```

首次登录后马上修改管理员密码。Volcengine 或本地模型配置也只填在 Render 环境变量 `AI_BASE_URL`、`AI_MODEL`、`AI_API_KEY` 中；`AI_API_KEY` 不要提交到代码仓库。

## GitHub 推送示例

在 `V1.07-Web` 目录执行：

```powershell
git init
git branch -M main
git add .
git commit -m "发布监测工作台 V1.07 Web"
git remote add origin https://github.com/<你的账号>/monitoring-v107-web.git
git push -u origin main
```

如果 GitHub 仓库已经有初始 README，先执行 `git pull --rebase origin main`，确认没有冲突后再推送。

## 自定义域名

在 Render 服务的 **Settings → Custom Domains** 添加域名，按 Render 显示的 DNS 记录配置域名解析。域名生效后，把 `FRONTEND_HOST` 和 `PUBLIC_BASE_URL` 改为 `https://你的域名`，再重新部署；二维码会使用新的公网地址。

## 数据和费用边界

项目监测数据、资料索引和上传文件分别使用 PostgreSQL 与 `/app/data` 持久磁盘。不要把数据库文件放进 GitHub。`render.yaml` 使用 Render Starter Web 服务和 10GB 持久盘；Render 的具体计费、区域和免费计划限制以控制台当前页面为准。若只用免费的静态 GitHub Pages，完整功能无法工作。
