<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import { ApiError, api } from "../api";
import type { DashboardSummary, ReplayEvent } from "../types";

const summary = ref<DashboardSummary | null>(null);
const error = ref("");
const events = ref<ReplayEvent[]>([]);
let source: EventSource | null = null;

async function load(): Promise<void> {
  try {
    summary.value = await api.summary();
    error.value = "";
  } catch (err) {
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

function subscribe(): void {
  source = new EventSource(api.streamUrl(0, 60));
  source.onmessage = (message: MessageEvent<string>) => {
    try {
      const event = JSON.parse(message.data) as ReplayEvent;
      events.value = [event, ...events.value].slice(0, 30);
    } catch {
      events.value = events.value;
    }
  };
}

onMounted(() => {
  void load();
  subscribe();
});

onUnmounted(() => {
  source?.close();
});
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">运行看板</h1>
      <div class="row">
        <span class="muted" v-if="summary">{{ summary.generated_at }}</span>
        <button class="btn" @click="load">刷新</button>
      </div>
    </div>

    <div class="error" v-if="error">{{ error }}</div>

    <template v-if="summary">
      <div class="grid">
        <div class="card">
          <div class="card-label">在办 Issue</div>
          <div class="card-value">{{ summary.in_progress }}</div>
        </div>
        <div class="card">
          <div class="card-label">已归档（不可达）</div>
          <div class="card-value">{{ summary.archived }}</div>
        </div>
        <div class="card">
          <div class="card-label">连续自运行（小时）</div>
          <div class="card-value">{{ summary.self_run_hours.toFixed(2) }}</div>
        </div>
        <div class="card">
          <div class="card-label">中断次数</div>
          <div class="card-value">{{ summary.interruptions }}</div>
        </div>
        <div class="card">
          <div class="card-label">自动处置</div>
          <div class="card-value">
            <span :class="['badge', summary.paused ? 'warn' : 'ok']">
              {{ summary.paused ? "已暂停" : "运行中" }}
            </span>
          </div>
        </div>
      </div>

      <div class="grid" style="margin-top: 14px">
        <div class="card">
          <div class="card-label">级别分布</div>
          <div class="row">
            <span class="badge l0">L0 {{ summary.level_distribution.L0 ?? 0 }}</span>
            <span class="badge l1">L1 {{ summary.level_distribution.L1 ?? 0 }}</span>
            <span class="badge l2">L2 {{ summary.level_distribution.L2 ?? 0 }}</span>
            <span class="badge l3">L3 {{ summary.level_distribution.L3 ?? 0 }}</span>
          </div>
        </div>
        <div class="card">
          <div class="card-label">熔断状态</div>
          <div class="row">
            <span
              v-for="(state, name) in summary.circuit_states"
              :key="name"
              :class="['badge', state === 'OPEN' ? 'fail' : 'ok']"
            >
              {{ name }} {{ state }}
            </span>
            <span class="muted" v-if="Object.keys(summary.circuit_states).length === 0">暂无熔断记录</span>
          </div>
        </div>
      </div>

      <div class="grid" style="margin-top: 14px; grid-template-columns: 1fr 1fr">
        <div class="card">
          <div class="card-label">失败原因 Top N</div>
          <table class="table" v-if="summary.failure_reasons.length">
            <thead>
              <tr>
                <th>原因码</th>
                <th>次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in summary.failure_reasons" :key="item[0]">
                <td>{{ item[0] }}</td>
                <td>{{ item[1] }}</td>
              </tr>
            </tbody>
          </table>
          <div class="empty" v-else>暂无失败记录</div>
        </div>

        <div class="card">
          <div class="card-label">M1–M9 指标</div>
          <table class="table" v-if="summary.metrics.length">
            <thead>
              <tr>
                <th>指标</th>
                <th>值</th>
                <th>可计算</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="metric in summary.metrics" :key="metric.metric_id">
                <td>{{ metric.metric_id }}</td>
                <td>{{ metric.value ?? "—" }}</td>
                <td>{{ metric.computable ? "是" : "否" }}</td>
              </tr>
            </tbody>
          </table>
          <div class="empty" v-else>指标尚未计算</div>
        </div>
      </div>

      <h2 class="page-title" style="margin-top: 22px; font-size: 16px">实时事件（SSE）</h2>
      <table class="table">
        <thead>
          <tr>
            <th>run</th>
            <th>seq</th>
            <th>类型</th>
            <th>主体</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="event in events" :key="`${event.seq}-${event.occurred_at}`">
            <td class="muted">{{ event.event_type === "CONTROL" ? "SYS" : "—" }}</td>
            <td>{{ event.seq }}</td>
            <td>{{ event.event_type }}</td>
            <td>{{ event.actor }}</td>
            <td class="muted">{{ event.occurred_at }}</td>
          </tr>
        </tbody>
      </table>
      <div class="empty" v-if="events.length === 0">暂无新增事件（等待后端产生事件）</div>
    </template>
  </div>
</template>