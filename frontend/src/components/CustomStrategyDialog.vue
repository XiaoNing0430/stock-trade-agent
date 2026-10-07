<template>
  <div v-if="screener.strategyEditorOpen" class="dialog-backdrop" @click.self="screener.closeStrategyEditor()">
    <section class="dialog-panel custom-strategy-panel" role="dialog" aria-modal="true" aria-label="自定义策略编辑器">
      <header class="custom-strategy-head">
        <h3>{{ screener.strategyEditorId ? '编辑自定义策略' : '新建自定义策略' }}</h3>
        <button class="text-button" type="button" @click="screener.closeStrategyEditor()">关闭</button>
      </header>

      <div v-if="loading" class="custom-strategy-state">加载中…</div>
      <template v-else>
        <div v-if="conflictText" class="custom-strategy-error" data-testid="conflict-banner">{{ conflictText }}</div>
        <div v-if="errorText" class="custom-strategy-error">{{ errorText }}</div>

        <div v-if="!screener.strategyEditorId" class="fork-row">
          <select v-model="forkId" class="input" aria-label="从内置策略复制">
            <option value="">从内置策略复制…</option>
            <option v-for="s in builtinRows" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <button class="button button-secondary" type="button" :disabled="!forkId" @click="applyFork">预填</button>
        </div>

        <div class="custom-strategy-grid">
          <label class="field">
            <span>名称</span>
            <input v-model="form.name" class="input" maxlength="64" aria-label="策略名称" />
          </label>
          <label class="field">
            <span>描述</span>
            <input v-model="form.description" class="input" maxlength="256" aria-label="策略描述" />
          </label>
          <label class="field">
            <span>排序字段</span>
            <select v-model="form.sortBy" class="input" aria-label="排序字段">
              <option value="changePct">涨跌幅</option>
              <option value="amount">成交额</option>
              <option value="turnoverRate">换手率</option>
              <option value="pe">市盈率</option>
              <option value="pb">市净率</option>
            </select>
          </label>
          <label class="field">
            <span>Top N（1-100）</span>
            <input v-model.number="form.topN" class="input" type="number" min="1" max="100" aria-label="Top N" />
          </label>
          <label class="field">
            <span>精筛上限（1-1000）</span>
            <input v-model.number="form.deepCap" class="input" type="number" min="1" max="1000" aria-label="精筛上限" />
          </label>
        </div>

        <h4 class="custom-strategy-subtitle">粗筛区间（留空 = 不设限）</h4>
        <div class="quick-filter-row" v-for="f in QUICK_FIELDS" :key="f.key">
          <span>{{ f.label }}</span>
          <input
            v-model.number="form.quickFilters[f.key]!.lo"
            class="input"
            type="number"
            step="any"
            :placeholder="'最小'"
            :aria-label="`${f.label}最小值`"
          />
          <span>–</span>
          <input
            v-model.number="form.quickFilters[f.key]!.hi"
            class="input"
            type="number"
            step="any"
            :placeholder="'最大'"
            :aria-label="`${f.label}最大值`"
          />
        </div>

        <h4 class="custom-strategy-subtitle">因子条件（≤20；权重 0.01–100）</h4>
        <div v-for="(factor, index) in form.factors" :key="index" class="factor-row">
          <select v-model="factor.name" class="input" :aria-label="`因子${index + 1}`">
            <option v-for="f in FACTORS" :key="f" :value="f">{{ f }}</option>
          </select>
          <input v-model.number="factor.period" class="input" type="number" min="2" max="250" aria-label="周期" />
          <select v-model="factor.operator" class="input" :aria-label="`算子${index + 1}`">
            <option value=">">&gt;</option>
            <option value="<">&lt;</option>
            <option value=">=">&ge;</option>
            <option value="<=">&le;</option>
          </select>
          <input v-model.number="factor.threshold" class="input" type="number" step="any" aria-label="阈值" />
          <input
            v-model.number="factor.weight"
            class="input"
            type="number"
            min="0.01"
            max="100"
            step="0.01"
            aria-label="权重"
          />
          <button class="text-button" type="button" @click="form.factors.splice(index, 1)">移除</button>
        </div>
        <button class="button button-secondary" type="button" :disabled="form.factors.length >= 20" @click="addFactor">
          添加因子
        </button>

        <footer class="custom-strategy-actions">
          <button class="button button-primary" type="button" :disabled="saving || !form.name.trim()" @click="save">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </footer>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { useScreenerStore } from '@/stores/useScreenerStore';

// 与 backend/screener/factors.py FactorLibrary.available_factors() 保持一致
const FACTORS = ['rsi', 'ma_slope', 'ma_arrange', 'bollinger_pos', 'momentum', 'deviation', 'volume_surge'];
// 与 backend/screener/loader.py ALLOWED_QUICK_FILTER_FIELDS 保持一致
const QUICK_FIELDS = [
  { key: 'pe', label: '市盈率' },
  { key: 'pb', label: '市净率' },
  { key: 'turnoverRate', label: '换手率' },
  { key: 'changePct', label: '涨跌幅' },
  { key: 'amount', label: '成交额' },
] as const;

const screener = useScreenerStore();

/** 数字输入归一：清空（`''` / null / undefined）或非有限值 → null（视为未填，绝不猜数）。 */
function toNumberOrNull(value: unknown): number | null {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

const loading = ref(false);
const saving = ref(false);
const errorText = ref('');
const conflictText = ref('');
const forkId = ref('');

const form = reactive({
  name: '',
  description: '',
  quickFilters: Object.fromEntries(
    QUICK_FIELDS.map(({ key }) => [key, { lo: null as number | null, hi: null as number | null }])
  ),
  factors: [] as { name: string; period: number; operator: string; threshold: number; weight: number }[],
  sortBy: 'changePct',
  topN: 10,
  deepCap: 200,
  version: null as number | null,
});

const builtinRows = ref<any[]>([]);

function resetForm() {
  form.name = '';
  form.description = '';
  for (const { key } of QUICK_FIELDS) {
    form.quickFilters[key] = { lo: null, hi: null };
  }
  form.factors = [];
  form.sortBy = 'changePct';
  form.topN = 10;
  form.deepCap = 200;
  form.version = null;
  errorText.value = '';
  conflictText.value = '';
  forkId.value = '';
}

function applyRow(row: any) {
  const config = row.config || {};
  form.name = row.name || '';
  form.description = row.description || '';
  for (const { key } of QUICK_FIELDS) {
    const bounds = config.quick_filters?.[key];
    form.quickFilters[key] = { lo: bounds?.[0] ?? null, hi: bounds?.[1] ?? null };
  }
  form.factors = (config.advanced_factors || []).map((f: any) => ({
    name: f.name,
    period: Number(f.period ?? 14),
    operator: f.operator,
    threshold: Number(f.threshold),
    weight: Number(f.weight ?? 1),
  }));
  form.sortBy = config.sort_by || 'changePct';
  form.topN = config.top_n ?? 10;
  form.deepCap = config.deep_cap ?? 200;
  form.version = row.version ?? null;
}

function applyFork() {
  const source = builtinRows.value.find((s: any) => s.id === forkId.value);
  if (!source) return;
  form.name = `${source.name}（副本）`;
  form.description = source.description || '';
  for (const { key } of QUICK_FIELDS) {
    const bounds = source.quickFilters?.[key];
    form.quickFilters[key] = { lo: bounds?.[0] ?? null, hi: bounds?.[1] ?? null };
  }
  form.factors = (source.advancedFactors || []).map((f: any) => ({
    name: f.name,
    period: Number(f.period ?? 14),
    operator: f.operator,
    threshold: Number(f.threshold),
    weight: Number(f.weight ?? 1),
  }));
  form.sortBy = source.sortBy || 'changePct';
  form.topN = source.topN ?? 10;
  form.deepCap = source.deepCap ?? 200;
}

function addFactor() {
  form.factors.push({ name: 'rsi', period: 14, operator: '<', threshold: 30, weight: 1 });
}

async function init() {
  resetForm();
  builtinRows.value = screener.strategies.filter((s: any) => s.custom !== true);
  if (screener.strategyEditorId) {
    loading.value = true;
    try {
      const row = await screener.loadCustomStrategyForEdit(screener.strategyEditorId);
      applyRow(row);
    } catch (error: any) {
      errorText.value = error?.message || '加载失败';
    } finally {
      loading.value = false;
    }
  }
}

watch(
  () => screener.strategyEditorOpen,
  (open) => {
    if (open) void init();
  }
);

async function save() {
  saving.value = true;
  errorText.value = '';
  conflictText.value = '';
  try {
    const quickFilters: Record<string, [number | null, number | null]> = {};
    for (const { key } of QUICK_FIELDS) {
      const { lo, hi } = form.quickFilters[key]!;
      const loNum = toNumberOrNull(lo);
      const hiNum = toNumberOrNull(hi);
      // 「留空 = 不设限」：清空数字框时 Vue .number 写回 ''，必须归一为 null，绝不提交 ''
      if (loNum !== null || hiNum !== null) quickFilters[key] = [loNum, hiNum];
    }

    const advancedFactors: Record<string, unknown>[] = [];
    for (const [index, factor] of form.factors.entries()) {
      const threshold = toNumberOrNull(factor.threshold);
      if (threshold === null) {
        // 阈值无服务端默认值：不猜数、不静默取默认，就地拦截并给中文提示
        errorText.value = `第 ${index + 1} 条因子的阈值不能为空（必填）`;
        return;
      }
      const row: Record<string, unknown> = { name: factor.name, operator: factor.operator, threshold };
      const period = toNumberOrNull(factor.period);
      if (period !== null) row.period = period; // 留空 → 省略键 → 服务端默认 14
      const weight = toNumberOrNull(factor.weight);
      if (weight !== null) row.weight = weight; // 留空 → 省略键 → 服务端默认 1
      advancedFactors.push(row);
    }

    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      description: form.description.trim(),
      quickFilters,
      advancedFactors,
      sortBy: form.sortBy,
    };
    const topN = toNumberOrNull(form.topN);
    if (topN !== null) payload.topN = topN; // 留空 → 省略键 → 服务端默认 10
    const deepCap = toNumberOrNull(form.deepCap);
    if (deepCap !== null) payload.deepCap = deepCap; // 留空 → 省略键 → 服务端默认 200
    if (screener.strategyEditorId) payload.version = form.version;
    await screener.saveCustomStrategy(payload);
  } catch (error: any) {
    if (error?.status === 409) {
      // 乐观锁冲突：只刷新版本号（否则重试必然再 409），绝不自动覆盖本地编辑
      const server = error?.payload?.detail?.server || error?.detail?.server;
      const serverVersion = server?.version ?? null;
      if (serverVersion !== null) form.version = serverVersion;
      conflictText.value = server
        ? `策略已被其他页面更新（服务器最新版本 v${server.version}：${server.name || '未命名'}）。你的本地修改已保留，确认后请再次保存。`
        : '策略已被其他页面更新，请刷新后重试；你的本地修改已保留。';
    } else {
      errorText.value = error?.message || '保存失败';
    }
  } finally {
    saving.value = false;
  }
}
</script>
