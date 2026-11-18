<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api";
import type { Issue, IssueStatus, Severity, IssueSubmission } from "../types";

const STATUSES: IssueStatus[] = [
  "RECEIVED",
  "TRIAGING",
  "REACHABLE",
  "SUSPECTED",
  "ARCHIVED",
  "REPRODUCING",
  "PROVEN",
  "REPRO_FAILED",
  "PATCHING",
  "AUDITING",
  "GATING",
  "ROLLING_BACK",
  "DISPOSED_L0",
  "DISPOSED_L1",
  "DISPOSED_L2",
  "DISPOSED_L3",
];

const issues = ref<Issue[]>([]);
const statusFilter = ref<string>("");
const error = ref("");
const notice = ref("");
const submitting = ref(false);
const form = ref<IssueSubmission>({
  repo: "verifix-target",
  code_version: "target-v1",
  rule_id: "py/sql-injection",
  severity: "HIGH",
  file: "app/main.py",
  line: 31,
  defect_class: "C02",
  snippet: "",
});

async function load(): Promise<void> {
  try {
    issues.value = await api.issues(statusFilter.value || undefined);
    error.value = "";
  } catch (err) {
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function submit(): Promise<void> {
  submitting.value = true;
  notice.value = "";
  try {
    const accepted = await api.submit(form.value);
    notice.value = `已受理 ${accepted.issue_id}（${accepted.status}）`;
    await load();
  } catch (err) {
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  } finally {
    submitting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">Issue 队列</h1>
      <div class="row">
        <select class="select" style="width: 200px" v-model="statusFilter" @change="load">
          <option value="">全部状态</option>
          <option v-for="status in STATUSES" :key="status" :value="status">{{ status }}</option>
        </select>
        <button class="btn" @click="load">刷新</button>
      </div>
    </div>

    <div class="error" v-if="error">{{ error }}</div>
    <div class="notice" v-if="notice">
      <span class="badge ok">{{ notice }}</span>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th>Issue</th>
          <th>类别</th>
          <th>严重度</th>
          <th>状态</th>
          <th>来源数</th>
          <th>发生时间</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="issue in issues" :key="issue.issue_id">
          <td>{{ issue.issue_id }}</td>
          <td>{{ issue.defect_class ?? "—" }}</td>
          <td>{{ issue.severity }}</td>
          <td>
            <span :class="['badge', issue.status.startsWith('DISPOSED_L') ? `l${issue.status.slice(-1)}` : 'warn']">
              {{ issue.status }}
            </span>
          </td>
          <td>{{ issue.source_count }}</td>
          <td class="muted">{{ issue.occurred_at }}</td>
          <td>
            <router-link :to="`/issues/${issue.issue_id}`">详情</router-link>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="empty" v-if="issues.length === 0">暂无 Issue</div>

    <div class="card" style="margin-top: 18px">
      <div class="card-label">人工提交 Issue</div>
      <div class="field">
        <label>仓库</label>
        <input class="input" v-model="form.repo" />
      </div>
      <div class="row">
        <div class="field" style="flex: 1">
          <label>代码版本</label>
          <input class="input" v-model="form.code_version" />
        </div>
        <div class="field" style="flex: 1">
          <label>规则</label>
          <input class="input" v-model="form.rule_id" />
        </div>
      </div>
      <div class="row">
        <div class="field" style="flex: 1">
          <label>类别</label>
          <select class="select" v-model="form.defect_class">
            <option :value="'C01'">C01 依赖 CVE</option>
            <option :value="'C02'">C02 SQL 注入</option>
            <option :value="'C03'">C03 命令注入</option>
            <option :value="'C05'">C05 硬编码凭据</option>
          </select>
        </div>
        <div class="field" style="flex: 1">
          <label>严重度</label>
          <select class="select" v-model="form.severity">
            <option :value="'HIGH' as Severity">HIGH</option>
            <option :value="'MEDIUM' as Severity">MEDIUM</option>
            <option :value="'CRITICAL' as Severity">CRITICAL</option>
            <option :value="'LOW' as Severity">LOW</option>
          </select>
        </div>
      </div>
      <div class="row">
        <div class="field" style="flex: 2">
          <label>文件</label>
          <input class="input" v-model="form.file" />
        </div>
        <div class="field" style="flex: 1">
          <label>行号</label>
          <input class="input" type="number" v-model.number="form.line" />
        </div>
      </div>
      <div class="field">
        <label>代码片段</label>
        <input class="input" v-model="form.snippet" />
      </div>
      <button class="btn primary" @click="submit" :disabled="submitting">
        {{ submitting ? "提交中…" : "提交" }}
      </button>
    </div>
  </div>
</template>