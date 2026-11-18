<script setup lang="ts">
import { onMounted, ref } from "vue";

interface MetaInfo {
  brand: string;
  branch_namespace: string;
  release_auto_branch: string;
  model_provider: string;
}

interface DashboardSummary {
  notifier_degraded?: boolean;
  undelivered_alerts?: number;
}

const brand = ref("VeriFix");
const meta = ref<MetaInfo | null>(null);
const notifierDegraded = ref(false);
const undeliveredAlerts = ref(0);

onMounted(async () => {
  try {
    const response = await fetch("/api/v1/meta");
    const body = (await response.json()) as { data: MetaInfo | null };
    if (body.data) {
      meta.value = body.data;
      brand.value = body.data.brand;
    }
  } catch {
    meta.value = null;
  }
  try {
    const response = await fetch("/api/v1/dashboard/summary");
    const body = (await response.json()) as { data: DashboardSummary | null };
    const data = body.data;
    notifierDegraded.value = Boolean(data?.notifier_degraded);
    undeliveredAlerts.value = Number(data?.undelivered_alerts ?? 0);
  } catch {
    notifierDegraded.value = false;
    undeliveredAlerts.value = 0;
  }
});
</script>

<template>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">{{ brand }}</div>
      <div class="brand-sub">
        <template v-if="meta">{{ meta.branch_namespace }} · {{ meta.model_provider }}</template>
        <template v-else>后端未连接</template>
      </div>
      <router-link class="nav-item" to="/">运行看板</router-link>
      <router-link class="nav-item" to="/issues">Issue 队列</router-link>
      <router-link class="nav-item" to="/replay">运行回放</router-link>
      <router-link class="nav-item" to="/control">控制面板</router-link>
      <router-link class="nav-item" to="/eval">评测</router-link>
      <router-link class="nav-item" to="/devlog">留痕自检</router-link>
    </aside>
    <main class="main">
      <div v-if="notifierDegraded" class="notifier-banner" role="alert">
        <strong>告警通道不可达</strong>
        <span>{{ undeliveredAlerts }} 条通知未送达</span>
        <span class="notifier-hint">请检查 Webhook 与控制台通道，送达恢复前门禁/熔断告警仅记录在事件表</span>
      </div>
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.notifier-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 16px;
  padding: 10px 14px;
  border: 1px solid #e5534b;
  border-radius: 6px;
  background: #fdecea;
  color: #8a1f1a;
  font-size: 14px;
}

.notifier-banner strong {
  font-weight: 600;
}

.notifier-hint {
  color: #8a1f1a;
  opacity: 0.8;
}
</style>