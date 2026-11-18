<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api";
import type { ControlRecord } from "../types";

const events = ref<ControlRecord[]>([]);
const paused = ref(false);
const pauseReason = ref("");
const actor = ref("operator");
const reason = ref("maintenance");
const defectClass = ref("C02");
const notice = ref("");
const error = ref("");

async function load(): Promise<void> {
  try {
    const [summary, records] = await Promise.all([api.summary(), api.controlEvents()]);
    paused.value = summary.paused;
    pauseReason.value = summary.pause_reason;
    events.value = records;
    error.value = "";
  } catch (err) {
    error.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function pause(): Promise<void> {
  try {
    await api.pause(actor.value, reason.value);
    notice.value = "已暂停自动处置（新任务排队，不丢弃）";
    await load();
  } catch (err) {
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function resume(): Promise<void> {
  try {
    await api.resume();
    notice.value = "已恢复自动处置";
    await load();
  } catch (err) {
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function reset(): Promise<void> {
  try {
    await api.resetCircuit(defectClass.value, actor.value, reason.value);
    notice.value = `已解除 ${defectClass.value} 熔断`;
    await load();
  } catch (err) {
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

async function heartbeat(): Promise<void> {
  try {
    const beat = await api.heartbeat();
    notice.value = `心跳正常，连续自运行 ${beat.self_run_hours.toFixed(2)} 小时`;
  } catch (err) {
    notice.value = err instanceof ApiError ? `${err.code} ${err.message}` : String(err);
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">控制面板</h1>
      <div class="row">
        <span :class="['badge', paused ? 'warn' : 'ok']">{{ paused ? "已暂停" : "运行中" }}</span>
        <button class="btn" @click="load">刷新</button>
      </div>
    </div>

    <div class="error" v-if="error">{{ error }}</div>
    <div class="notice" v-if="notice"><span class="badge warn">{{ notice }}</span></div>
    <div class="muted" v-if="paused && pauseReason">暂停原因：{{ pauseReason }}</div>

    <div class="grid" style="margin-top: 14px">
      <div class="card">
        <div class="card-label">暂停 / 恢复</div>
        <div class="field">
          <label>操作人</label>
          <input class="input" v-model="actor" />
        </div>
        <div class="field">
          <label>理由</label>
          <input class="input" v-model="reason" />
        </div>
        <div class="row">
          <button class="btn danger" @click="pause">暂停</button>
          <button class="btn primary" @click="resume">恢复</button>
        </div>
      </div>

      <div class="card">
        <div class="card-label">熔断解除</div>
        <div class="field">
          <label>缺陷类别</label>
          <select class="select" v-model="defectClass">
            <option value="C01">C01 依赖 CVE</option>
            <option value="C02">C02 SQL 注入</option>
            <option value="C03">C03 命令注入</option>
            <option value="C05">C05 硬编码凭据</option>
          </select>
        </div>
        <button class="btn" @click="reset">解除熔断</button>
      </div>

      <div class="card">
        <div class="card-label">自运行心跳</div>
        <button class="btn" @click="heartbeat">发送心跳</button>
      </div>
    </div>

    <h2 class="page-title" style="margin-top: 22px; font-size: 16px">控制事件</h2>
    <table class="table">
      <thead>
        <tr>
          <th>动作</th>
          <th>主体</th>
          <th>范围</th>
          <th>理由</th>
          <th>时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in events" :key="`${item.action}-${item.occurred_at}`">
          <td>{{ item.action }}</td>
          <td>{{ item.actor }}</td>
          <td>{{ item.scope }}</td>
          <td>{{ item.reason }}</td>
          <td class="muted">{{ item.occurred_at }}</td>
        </tr>
      </tbody>
    </table>
    <div class="empty" v-if="events.length === 0">暂无控制事件</div>
  </div>
</template>