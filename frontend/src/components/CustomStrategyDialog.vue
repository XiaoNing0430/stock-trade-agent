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
      if (lo !== null || hi !== null) quickFilters[key] = [lo, hi];
    }
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      description: form.description.trim(),
      quickFilters,
      advancedFactors: form.factors.map((f) => ({ ...f })),
      sortBy: form.sortBy,
      topN: form.topN,
      deepCap: form.deepCap,
    };
    if (screener.strategyEditorId) payload.version = form.version;
    await screener.saveCustomStrategy(payload);
  } catch (error: any) {
    if (error?.status === 409) {
      // 乐观锁冲突：不覆盖本地输入，加载服务器最新版本供参考后重试
      const server = error?.payload?.detail?.server || error?.detail?.server;
      conflictText.value = '策略已被其他页面更新，已加载服务器最新版本；如需保留请重新调整后再保存';
      if (server) applyRow(server);
    } else {
      errorText.value = error?.message || '保存失败';
    }
  } finally {
    saving.value = false;
  }
}
</script>
