<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api";
import type { MetricRow } from "../types";

const metrics = ref<MetricRow[]>([]);
const error = ref("");

async function load(): Promise<void> {
  try {
    metrics.value = await api.metrics();
    error.value = "";
  } catch (err) {
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">评测与指标</h1>
      <button class="btn" @click="load">刷新</button>
    </div>

    <div class="error" v-if="error">{{ error }}</div>

    <table class="table">
      <thead>
        <tr>
          <th>指标</th>
          <th>阶段</th>
          <th>窗口</th>
          <th>值</th>
          <th>可计算</th>
          <th>来源</th>
          <th>定义版本</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="metric in metrics" :key="`${metric.metric_id}-${metric.stage_tier}-${metric.window}`">
          <td>{{ metric.metric_id }}</td>
          <td>{{ metric.stage_tier }}</td>
          <td>{{ metric.window }}</td>
          <td>{{ metric.value ?? "—" }}</td>
          <td>
            <span :class="['badge', metric.computable ? 'ok' : 'warn']">
              {{ metric.computable ? "是" : "否" }}
            </span>
          </td>
          <td class="muted">{{ metric.source_ref }}</td>
          <td class="muted">{{ metric.definition_version }}</td>
        </tr>
      </tbody>
    </table>
    <div class="empty" v-if="metrics.length === 0">
      指标尚未计算。不可计算的指标必须显示原因，不得补零（见 spec 5.9）。
    </div>

    <div class="card" style="margin-top: 18px">
      <div class="card-label">评测集说明</div>
      <div class="muted">
        初赛 50 条评测集的配比校验与 M1–M9 复算在服务端执行；本页只展示服务端已落库的真实指标，
        不展示任何占位数据。空表表示尚未产生指标。
      </div>
    </div>
  </div>
</template>