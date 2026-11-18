<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api";
import type { EvidenceView, IssueDetail } from "../types";

const props = defineProps<{ id: string }>();

const detail = ref<IssueDetail | null>(null);
const evidence = ref<EvidenceView | null>(null);
const error = ref("");
const notice = ref("");
const actor = ref("security-lead");
const reason = ref("manual review");

async function load(): Promise<void> {
  try {
    detail.value = await api.issue(props.id);
    error.value = "";
  } catch (err) {
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function checkEvidence(): Promise<void> {
  try {
    evidence.value = await api.disposition(props.id);
    notice.value = "证据校验通过";
  } catch (err) {
    evidence.value = null;
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function retry(): Promise<void> {
  try {
    await api.retry(props.id);
    notice.value = "已重试并入队";
    await load();
  } catch (err) {
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function handoff(): Promise<void> {
  try {
    await api.handoff(props.id, actor.value, reason.value);
    notice.value = "已转人工并写入控制事件";
  } catch (err) {
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">Issue 详情 · {{ id }}</h1>
      <div class="row">
        <button class="btn" @click="load">刷新</button>
        <router-link class="btn" to="/issues">返回队列</router-link>
      </div>
    </div>

    <div class="error" v-if="error">{{ error }}</div>
    <div class="notice" v-if="notice"><span class="badge warn">{{ notice }}</span></div>

    <template v-if="detail">
      <div class="grid">
        <div class="card">
          <div class="card-label">状态</div>
          <div class="card-value" style="font-size: 18px">{{ detail.issue.status }}</div>
        </div>
        <div class="card">
          <div class="card-label">类别 / 严重度</div>
          <div class="card-value" style="font-size: 18px">
            {{ detail.issue.defect_class ?? "—" }} / {{ detail.issue.severity }}
          </div>
        </div>
        <div class="card">
          <div class="card-label">来源数</div>
          <div class="card-value">{{ detail.issue.source_count }}</div>
        </div>
        <div class="card">
          <div class="card-label">仓库 / 版本</div>
          <div class="card-value" style="font-size: 15px">
            {{ detail.issue.repo }}@{{ detail.issue.code_version }}
          </div>
        </div>
      </div>

      <div class="card" style="margin-top: 14px">
        <div class="card-label">原始告警</div>
        <table class="table" v-if="detail.alerts.length">
          <thead>
            <tr>
              <th>来源</th>
              <th>规则</th>
              <th>定位</th>
              <th>严重度</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="alert in detail.alerts" :key="alert.alert_ref">
              <td>{{ alert.source_kind }}</td>
              <td>{{ alert.rule_id }}</td>
              <td>{{ alert.location.file }}:{{ alert.location.line ?? alert.location.component }}</td>
              <td>{{ alert.raw_severity }}</td>
            </tr>
          </tbody>
        </table>
        <div class="empty" v-else>无告警记录</div>
      </div>

      <div class="card" style="margin-top: 14px">
        <div class="card-label">可达性结论</div>
        <template v-if="detail.verdict">
          <div class="row">
            <span :class="['badge', detail.verdict.conclusion === 'REACHABLE' ? 'ok' : 'warn']">
              {{ detail.verdict.conclusion }}
            </span>
            <span class="muted">置信度 {{ detail.verdict.confidence }}</span>
            <span class="muted">{{ detail.verdict.decided_by }}</span>
          </div>
          <div class="code" style="margin-top: 10px" v-if="detail.verdict.taint_path.length">
            {{ detail.verdict.taint_path.join(" → ") }}
          </div>
          <div class="code" style="margin-top: 10px" v-else>{{ detail.verdict.basis }}</div>
        </template>
        <div class="empty" v-else>尚无判定结论</div>
      </div>

      <div class="grid" style="margin-top: 14px; grid-template-columns: 1fr 1fr">
        <div class="card">
          <div class="card-label">复现证据 Proof</div>
          <template v-if="detail.proof">
            <div>测试：{{ detail.proof.test_path }}</div>
            <div>补丁前：{{ detail.proof.pre_patch_result }}</div>
            <div class="code" style="margin-top: 8px">{{ detail.proof.fingerprint }}</div>
          </template>
          <div class="empty" v-else>尚未生成红态证据</div>
        </div>
        <div class="card">
          <div class="card-label">补丁 Patch</div>
          <template v-if="detail.patch">
            <div>分支：{{ detail.patch.branch }}</div>
            <div>变更：{{ detail.patch.lines_changed }} 行 / {{ detail.patch.files_changed }} 文件</div>
            <div>范式：{{ detail.patch.fix_paradigm }}　强度：{{ detail.patch.patch_strength }}</div>
            <div class="code" style="margin-top: 8px">{{ detail.patch.diff_ref }}</div>
          </template>
          <div class="empty" v-else>尚未生成补丁</div>
        </div>
      </div>

      <div class="card" style="margin-top: 14px">
        <div class="card-label">处置与证据下钻</div>
        <template v-if="detail.disposition">
          <div>级别：{{ detail.disposition.level }}　动作：{{ detail.disposition.action }}</div>
          <div class="muted">原因码：{{ detail.disposition.reason_code }}</div>
          <div class="code" style="margin-top: 8px">{{ detail.disposition.evidence_ref }}</div>
          <button class="btn" style="margin-top: 10px" @click="checkEvidence">校验证据完整性</button>
          <div v-if="evidence" style="margin-top: 8px">
            <span :class="['badge', evidence.conclusion_trusted ? 'ok' : 'fail']">
              {{ evidence.conclusion_trusted ? "证据完整，结论可信" : "证据缺失，结论不可信" }}
            </span>
          </div>
        </template>
        <div class="empty" v-else>尚未处置</div>
      </div>

      <div class="card" style="margin-top: 14px">
        <div class="card-label">人工操作</div>
        <div class="row">
          <button class="btn" @click="retry">重试</button>
        </div>
        <div class="row" style="margin-top: 10px">
          <input class="input" style="max-width: 180px" v-model="actor" placeholder="操作人" />
          <input class="input" style="max-width: 320px" v-model="reason" placeholder="理由" />
          <button class="btn danger" @click="handoff">转人工</button>
        </div>
      </div>
    </template>
  </div>
</template>