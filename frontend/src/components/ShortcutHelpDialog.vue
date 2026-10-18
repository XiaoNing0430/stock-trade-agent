<template>
  <div v-if="helpOpen" class="dialog-backdrop" @click.self="close">
    <section
      ref="overlayPanel"
      class="dialog-panel shortcut-help-panel"
      role="dialog"
      aria-modal="true"
      aria-label="键盘快捷键"
    >
      <header class="dialog-head">
        <h2>键盘快捷键</h2>
        <button class="text-button" type="button" @click="close">关闭</button>
      </header>
      <table class="shortcut-table">
        <tbody>
          <tr v-for="row in rows" :key="row.keys">
            <th scope="row"><kbd>{{ row.keys }}</kbd></th>
            <td>{{ row.label }}</td>
          </tr>
        </tbody>
      </table>
      <p class="heading-note">数字键为桌面快捷键；手机端可用顶部「?」按钮随时查看本表。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useOverlayA11y } from '@/modules/overlayA11y';
import { VIEW_SHORTCUTS, helpOpen } from '@/modules/shortcuts';
import { NAV_ITEMS } from '@/modules/constants';

const overlayPanel = ref<HTMLElement | null>(null);
const rows = computed(() => [
  { keys: '/', label: '聚焦搜索' },
  ...Object.entries(VIEW_SHORTCUTS).map(([digit, view]) => ({
    keys: digit,
    label: `切换到${NAV_ITEMS.find((item) => item.id === view)?.label ?? view}`,
  })),
  { keys: '?', label: '打开 / 关闭帮助' },
  { keys: 'Esc', label: '关闭当前浮层' },
  { keys: 'Enter', label: '在搜索框 / 回测参数框提交' },
]);

function close(): void {
  helpOpen.value = false;
}

useOverlayA11y({ id: 'shortcut-help', isOpen: () => helpOpen.value, panelRef: overlayPanel, onClose: close });
</script>
