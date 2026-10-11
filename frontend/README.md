# V1.07 Web 前端

React、TypeScript、Vite、TanStack Router/Query，保留模板 shadcn/ui Button。页面以中文界面和响应式 CSS 改造。

Node.js 20.19+：
```powershell
npm ci --workspaces=false
npm run dev
npm run build
npm test
```
构建输出到 ../backend/app/frontend，由 FastAPI 同源服务。开发 API 代理端口8007。浏览器测试默认使用 Microsoft Edge；设置 PLAYWRIGHT_CHANNEL=chrome 可切换 Chrome。WEB_TEST_URL 默认为本机8007，验收建议设为隔离服务8017。

访问令牌保存在 sessionStorage；项目归属由后端检查，菜单隐藏仅用于界面体验。

