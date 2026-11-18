import { createRouter, createWebHistory } from "vue-router";

import ControlView from "./views/ControlView.vue";
import DashboardView from "./views/DashboardView.vue";
import DevlogView from "./views/DevlogView.vue";
import EvalView from "./views/EvalView.vue";
import IssueDetailView from "./views/IssueDetailView.vue";
import IssuesView from "./views/IssuesView.vue";
import ReplayView from "./views/ReplayView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView, meta: { title: "运行看板" } },
    { path: "/issues", name: "issues", component: IssuesView, meta: { title: "Issue 队列" } },
    { path: "/issues/:id", name: "issue", component: IssueDetailView, props: true, meta: { title: "Issue 详情" } },
    { path: "/replay", name: "replay", component: ReplayView, meta: { title: "运行回放" } },
    { path: "/control", name: "control", component: ControlView, meta: { title: "控制面板" } },
    { path: "/eval", name: "eval", component: EvalView, meta: { title: "评测" } },
    { path: "/devlog", name: "devlog", component: DevlogView, meta: { title: "留痕自检" } },
  ],
});