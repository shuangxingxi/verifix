<script setup lang="ts">
import { onMounted, ref } from "vue";

interface ProbeResult {
  name: string;
  target: string;
  ok: boolean;
  detail: string;
}

const probes = ref<ProbeResult[]>([]);
const loading = ref(false);

async function runProbe(name: string, target: string, path: string): Promise<ProbeResult> {
  try {
    const response = await fetch(path);
    const body = (await response.json()) as { code: number | string; trace_id: string };
    return {
      name,
      target,
      ok: response.ok,
      detail: `HTTP ${response.status} · code=${body.code} · trace=${body.trace_id || "—"}`,
    };
  } catch (err) {
    return { name, target, ok: false, detail: String(err) };
  }
}

async function run(): Promise<void> {
  loading.value = true;
  probes.value = [
    await runProbe("服务存活", "GET /healthz", "/healthz"),
    await runProbe("配置与产品名", "GET /api/v1/meta", "/api/v1/meta"),
    await runProbe("看板与证据链", "GET /api/v1/dashboard/summary", "/api/v1/dashboard/summary"),
  ];
  loading.value = false;
}

onMounted(run);
</script>

<template>
  <div>
    <div class="page-head">
      <h1 class="page-title">留痕自检</h1>
      <button class="btn" @click="run" :disabled="loading">{{ loading ? "检测中…" : "重新检测" }}</button>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th>检查项</th>
          <th>端点</th>
          <th>结果</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="probe in probes" :key="probe.name">
          <td>{{ probe.name }}</td>
          <td class="muted">{{ probe.target }}</td>
          <td>
            <span :class="['badge', probe.ok ? 'ok' : 'fail']">{{ probe.ok ? "通过" : "失败" }}</span>
          </td>
          <td class="muted">{{ probe.detail }}</td>
        </tr>
      </tbody>
    </table>

    <div class="card" style="margin-top: 18px">
      <div class="card-label">五步留痕文档（仓库内）</div>
      <ul class="timeline">
        <li>① 需求理解：docs/devlog/01-requirement.md</li>
        <li>② 代码生成：提交前缀 [step-2/codegen]（规范见 docs/devlog/00-conventions.md）</li>
        <li>③ 项目构建：构建日志与产物摘要（待接入流水线）</li>
        <li>④ 问题修复：自举 Issue → 补丁 → PR</li>
        <li>⑤ 部署上线：发布单与回滚演练</li>
      </ul>
      <div class="muted" style="margin-top: 10px">
        规格归档：docs/devlog/specs/（spec.md / design.md / tasks.md 冻结副本）
      </div>
    </div>
  </div>
</template>