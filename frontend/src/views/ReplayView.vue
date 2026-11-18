<script setup lang="ts">
import { ref } from "vue";

import { ApiError, api } from "../api";
import type { RunReplay } from "../types";

const runId = ref("");
const replay = ref<RunReplay | null>(null);
const error = ref("");

async function load(): Promise<void> {
  if (!runId.value.trim()) {
    error.value = "请输入 run_id";
    return;
  }
  try {
    replay.value = await api.replay(runId.value.trim());
    error.value = "";
  } catch (err) {
    replay.value = null;
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">运行回放</h1>
    </div>

    <div class="row">
      <input class="input" style="max-width: 360px" v-model="runId" placeholder="RUN-xxxxxxxx" />
      <button class="btn primary" @click="load">加载回放</button>
    </div>
    <div class="error" v-if="error">{{ error }}</div>

    <template v-if="replay">
      <div class="grid" style="margin-top: 16px">
        <div class="card">
          <div class="card-label">Issue</div>
          <div class="card-value" style="font-size: 16px">{{ replay.issue_id }}</div>
        </div>
        <div class="card">
          <div class="card-label">终态</div>
          <div class="card-value" style="font-size: 16px">{{ replay.terminal_state ?? "运行中" }}</div>
        </div>
        <div class="card">
          <div class="card-label">事件链完整</div>
          <div class="card-value" style="font-size: 16px">
            <span :class="['badge', replay.chain_valid ? 'ok' : 'fail']">
              {{ replay.chain_valid ? "校验通过" : "链已损坏" }}
            </span>
          </div>
        </div>
        <div class="card">
          <div class="card-label">未执行步骤</div>
          <div class="card-value" style="font-size: 16px">
            {{ replay.missing_steps.length ? replay.missing_steps.join(" / ") : "无" }}
          </div>
        </div>
      </div>

      <h2 class="page-title" style="margin-top: 22px; font-size: 16px">七步时间线</h2>
      <ul class="timeline">
        <li v-for="step in replay.steps" :key="step.kind">
          <div class="row">
            <span :class="['badge', step.status === 'DONE' ? 'ok' : step.status === 'FAILED' ? 'fail' : 'warn']">
              {{ step.kind }}
            </span>
            <span class="muted">{{ step.status }}{{ step.executed ? "" : "（未执行）" }}</span>
            <span class="muted" v-if="step.evidence_ref">{{ step.evidence_ref }}</span>
          </div>
        </li>
      </ul>

      <h2 class="page-title" style="margin-top: 22px; font-size: 16px">事件序列</h2>
      <table class="table">
        <thead>
          <tr>
            <th>seq</th>
            <th>类型</th>
            <th>步骤</th>
            <th>主体</th>
            <th>证据引用</th>
            <th>发生时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="event in replay.events" :key="event.seq">
            <td>{{ event.seq }}</td>
            <td>{{ event.event_type }}</td>
            <td>{{ event.step ?? "—" }}</td>
            <td>{{ event.actor }}</td>
            <td class="muted">{{ event.payload_ref ?? "—" }}</td>
            <td class="muted">{{ event.occurred_at }}</td>
          </tr>
        </tbody>
      </table>
      <div class="empty" v-if="replay.events.length === 0">该运行暂无事件</div>
    </template>
  </div>
</template>