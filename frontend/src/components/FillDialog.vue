<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useOverlayA11y } from '@/modules/overlayA11y';
import type { FillInput, Plan } from '@/types/models';

const props = withDefaults(
  defineProps<{ open: boolean; preset?: Partial<FillInput>; plans?: Plan[] }>(),
  { preset: () => ({}), plans: () => [] }
);
const emit = defineEmits<{ 'update:open': [boolean]; submit: [FillInput] }>();

const overlayPanel = ref<HTMLElement | null>(null);
function close() {
  emit('update:open', false);
}
useOverlayA11y({ id: 'fill-dialog', isOpen: () => props.open, panelRef: overlayPanel, onClose: close });

const code = ref('');
const direction = ref<'buy' | 'sell'>('buy');
const price = ref<number | ''>('');
const qty = ref<number | ''>('');
const fee = ref<number | ''>(0);
const localTime = ref('');
const note = ref('');
const planId = ref('');
const hint = ref('');

function toLocalInput(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    code.value = props.preset.code ?? '';
    direction.value = props.preset.direction ?? 'buy';
    price.value = props.preset.price ?? '';
    qty.value = props.preset.qty ?? '';
    fee.value = props.preset.fee ?? 0;
    planId.value = props.preset.planId ?? '';
    localTime.value = toLocalInput(props.preset.tradedAtMs ?? Date.now());
    note.value = props.preset.note ?? '';
    hint.value = '';
  },
  { immediate: true }
);

const amount = computed(() => Number(price.value || 0) * Number(qty.value || 0));

function estimateFee() {
  const value = amount.value;
  if (!value) return;
  const commission = Math.max(5, value * 0.0003);
  const stamp = direction.value === 'sell' && code.value.trim().startsWith('6') ? value * 0.0005 : 0;
  const transfer = code.value.trim().startsWith('6') ? value * 0.00001 : 0;
  fee.value = Number((commission + stamp + transfer).toFixed(2));
}

function submit() {
  hint.value = '';
  if (!code.value.trim()) {
    hint.value = '请填写证券代码';
    return;
  }
  if (!(Number(price.value) > 0)) {
    hint.value = '成交价必须大于 0';
    return;
  }
  const quantity = Number(qty.value);
  if (!Number.isInteger(quantity) || quantity <= 0) {
    hint.value = '成交数量必须是正整数';
    return;
  }
  if (!localTime.value) {
    hint.value = '请选择成交时间';
    return;
  }
  const tradedAtMs = new Date(localTime.value).getTime();
  if (!Number.isFinite(tradedAtMs) || tradedAtMs > Date.now() + 86_400_000) {
    hint.value = '成交时间不能晚于明天';
    return;
  }
  emit('submit', {
    code: code.value.trim(),
    direction: direction.value,
    price: Number(price.value),
    qty: quantity,
    fee: Number(fee.value || 0),
    tradedAtMs,
    planId: planId.value || null,
    note: note.value.trim(),
  });
}
</script>

<template>
  <div v-if="open" class="dialog-backdrop" @click.self="close">
    <section
      ref="overlayPanel"
      class="dialog-panel fill-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="录入成交"
    >
      <header class="fill-dialog-head">
        <strong>录入成交</strong>
        <button class="text-button" type="button" @click="close">关闭</button>
      </header>

      <div class="fill-grid">
        <label class="field"
          ><span>方向</span>
          <select v-model="direction" data-testid="fill-direction">
            <option value="buy">买入</option>
            <option value="sell">卖出</option>
          </select>
        </label>
        <label class="field"
          ><span>证券代码</span>
          <input v-model="code" data-testid="fill-code" placeholder="如 600519" />
        </label>
        <label class="field"
          ><span>成交价</span>
          <input v-model.number="price" data-testid="fill-price" type="number" step="0.001" min="0" />
        </label>
        <label class="field"
          ><span>数量（股/份）</span>
          <input v-model.number="qty" data-testid="fill-qty" type="number" step="1" min="0" />
        </label>
        <label class="field"
          ><span>总费用（元）</span>
          <input v-model.number="fee" data-testid="fill-fee" type="number" step="0.01" min="0" />
        </label>
        <label class="field"
          ><span>成交时间</span>
          <input v-model="localTime" data-testid="fill-time" type="datetime-local" />
        </label>
        <label class="field fill-field-wide"
          ><span>关联计划（可选）</span>
          <select v-model="planId" data-testid="fill-plan">
            <option value="">不关联</option>
            <option v-for="plan in plans" :key="plan.id" :value="plan.id">
              {{ plan.code }} · {{ plan.direction === 'buy' ? '买入' : '卖出' }} · 计划价 {{ plan.entry }}
            </option>
          </select>
        </label>
        <label class="field fill-field-wide"
          ><span>备注</span>
          <input v-model="note" data-testid="fill-note" maxlength="500" placeholder="可选" />
        </label>
      </div>

      <div class="fill-dialog-actions">
        <button class="button button-secondary" type="button" data-testid="fill-estimate" @click="estimateFee">
          按费率估算费用
        </button>
        <span class="muted">金额 {{ amount.toFixed(2) }} 元；估算仅供参考，以券商账单为准</span>
      </div>

      <p v-if="hint" class="fill-hint" data-testid="fill-hint" role="alert">{{ hint }}</p>

      <footer class="fill-dialog-foot">
        <button class="button button-secondary" type="button" @click="close">取消</button>
        <button class="button button-primary" type="button" data-testid="fill-submit" @click="submit">
          保存成交
        </button>
      </footer>
    </section>
  </div>
</template>
