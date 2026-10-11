import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
  Link,
  redirect,
} from "@tanstack/react-router";
import { Login } from "./pages/Auth";
import { Shell } from "./components/Shell";
import { Projects } from "./pages/Projects";
import { ProjectWorkspace } from "./pages/ProjectWorkspace";
import { Users } from "./pages/Users";
import { ChartPage } from "./pages/ChartPage";
import { token } from "./api";
import { rememberLoginDestination } from "./authNavigation";
import "./index.css";
const root = createRootRoute({
  component: () => <Outlet />,
  notFoundComponent: () => (
    <div className="loading">
      <h1>页面不存在</h1>
      <Link to="/">返回我的项目</Link>
    </div>
  ),
});
const login = createRoute({
  getParentRoute: () => root,
  path: "/login",
  component: Login,
});
const layout = createRoute({
  getParentRoute: () => root,
  id: "workspace",
  component: Shell,
  beforeLoad: () => {
    if (!token()) {
      rememberLoginDestination();
      throw redirect({ to: "/login", replace: true });
    }
  },
});
const projects = createRoute({
  getParentRoute: () => layout,
  path: "/",
  component: Projects,
});
const all = createRoute({
  getParentRoute: () => layout,
  path: "/all-projects",
  component: () => <Projects all />,
});
const project = createRoute({
  getParentRoute: () => layout,
  path: "/projects/$projectId",
  component: ProjectWorkspace,
});
const users = createRoute({
  getParentRoute: () => layout,
  path: "/users",
  component: Users,
});
const chart = createRoute({
  getParentRoute: () => layout,
  path: "/charts/$projectId",
  validateSearch: (search: Record<string, unknown>) => ({
    measurement:
      typeof search.measurement === "string" && search.measurement.length <= 150
        ? search.measurement
        : "",
  }),
  component: ChartPage,
});
const router = createRouter({
  routeTree: root.addChildren([
    login,
    layout.addChildren([projects, all, project, users, chart]),
  ]),
});
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
const cache = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15000 },
  },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={cache}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
