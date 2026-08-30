<template>
  <section class="view-panel is-active">
    <div class="view-heading"><div><span class="section-kicker">PERSONAL HUB</span><h2>个人中心</h2><p class="heading-note">提醒中心与网站设置的统一入口。</p></div></div>
    <div class="settings-tabs settings-tabs-primary" role="tablist" aria-label="个人中心分组">
      <button type="button" role="tab" :class="['settings-tab', 'settings-tab-primary', { 'is-active': hubTab === 'alerts' }]" :aria-selected="hubTab === 'alerts'" @click="hubTab = 'alerts'">提醒中心</button>
      <button type="button" role="tab" :class="['settings-tab', 'settings-tab-primary', { 'is-active': hubTab === 'settings' }]" :aria-selected="hubTab === 'settings'" @click="hubTab = 'settings'">网站设置</button>
    </div>

    <template v-if="hubTab === 'alerts'">
      <section class="alerts-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">NOTIFICATIONS</span><h3>通知收件箱</h3></div><button class="text-button" type="button" @click="clearReadAlerts">清空已读</button></div>
        <div class="alert-filters" role="tablist" aria-label="提醒分类">
          <button v-for="option in [{ id: 'all', label: '全部' }, { id: 'trade', label: '盯盘' }, { id: 'system', label: '系统' }]" :key="option.id" type="button" role="tab" :class="['alert-filter-chip', { 'is-active': alertFilter === option.id }]" :aria-selected="alertFilter === option.id" @click="alertFilter = option.id">{{ option.label }}</button>
        </div>
        <div class="alert-list">
          <div v-for="alert in filteredAlerts" :key="alert.id" class="alert-item" :class="{ unread: !alert.read }">
            <div :class="['alert-icon', alert.kind === 'success' ? 'success' : alert.kind === 'info' || alert.kind === 'system' ? 'info' : '']"><i :data-lucide="alert.kind === 'success' ? 'check-circle-2' : alert.kind === 'alert' ? 'triangle-alert' : alert.kind === 'system' ? 'wrench' : 'bell-ring'" aria-hidden="true"></i></div>
            <div class="alert-copy"><strong>{{ alert.title }}</strong><span>{{ alert.message }}</span><div class="alert-meta"><span>{{ alert.time }}</span><button class="text-button" type="button" @click="markAlertRead(alert.id)">{{ alert.read ? '已读' : '标记已读' }}</button></div></div>
          </div>
          <div v-if="!filteredAlerts.length" class="empty-state"><i data-lucide="bell-off" aria-hidden="true"></i><strong>暂无提醒</strong><span>切换分类查看其他提醒。</span></div>
        </div>
      </section>
    </template>

    <template v-if="hubTab === 'settings'">
      <div class="settings-subbar">
        <div class="settings-tabs settings-tabs-sub" role="tablist" aria-label="设置分组">
          <button v-for="tab in settingsTabs" :key="tab.id" type="button" role="tab" :class="['settings-tab', 'settings-tab-sub', { 'is-active': settingsTab === tab.id }]" :aria-selected="settingsTab === tab.id" @click="settingsTab = tab.id">{{ tab.label }}</button>
        </div>
        <div class="view-heading-actions"><button class="button" :class="settingsDirty ? 'button-primary' : 'button-secondary'" type="button" :disabled="settingsLoading" @click="saveSettings"><i data-lucide="save" aria-hidden="true"></i>保存设置</button></div>
      </div>
      <div class="settings-grid">
      <section v-if="settingsTab === 'workspace'" class="settings-row"><div><strong>工作区名称</strong><span>用于本浏览器工作台</span></div><input v-model.trim="settingsDraft.workspaceName" aria-label="工作区名称"></section>
      <section v-if="settingsTab === 'workspace'" class="settings-row"><div><strong>默认账户资金</strong><span>新建计划和网格策略的参考资金</span></div><div class="number-input"><input v-model.number="settingsDraft.defaultCapital" type="number" min="1000" step="1000" aria-label="默认账户资金"><span>元</span></div></section>
      <section v-if="settingsTab === 'workspace'" class="settings-row"><div><strong>冲突处理策略</strong><span>多个页面同时修改工作区时的默认处理方式</span></div><select v-model="settingsDraft.conflictPolicy" aria-label="冲突处理策略"><option value="server">自动采用服务器版本（推荐）</option><option value="local">自动用本地覆盖</option><option value="ask">每次询问</option></select></section>
      <section v-if="settingsTab === 'workspace'" class="settings-row"><div><strong>桌面通知：盯盘触发</strong><span>价格触发与计划动态弹系统通知</span></div><label class="toggle"><input v-model="settingsDraft.notifyDesktopAlert" type="checkbox"><span class="toggle-track"><span></span></span></label></section>
      <section v-if="settingsTab === 'workspace'" class="settings-row"><div><strong>桌面通知：系统事件</strong><span>冲突自愈、行情降级等收件箱事件弹系统通知</span></div><label class="toggle"><input v-model="settingsDraft.notifyDesktopSystem" type="checkbox"><span class="toggle-track"><span></span></span></label></section>
      <section v-if="settingsTab === 'data'" class="settings-row"><div><strong>行情刷新间隔</strong><span>盯盘标的存在时自动刷新</span></div><div class="number-input"><input v-model.number="settingsDraft.refreshInterval" type="number" min="5" max="300" aria-label="行情刷新间隔"><span>秒</span></div></section>
      <section v-if="settingsTab === 'data'" class="settings-row"><div><strong>自动故障切换</strong><span>首选来源异常时尝试可用备选来源</span></div><label class="toggle"><input v-model="settingsDraft.fallbackEnabled" type="checkbox"><span class="toggle-track"><span></span></span></label></section>
      <section v-if="settingsTab === 'data'" class="settings-row"><div><strong>实时行情来源</strong><span>当前仅腾讯公开行情提供实时 A 股报价</span></div><select v-model="settingsDraft.realtimeSource" aria-label="实时行情来源"><option value="tencent">腾讯公开行情</option></select></section>
      <section v-if="settingsTab === 'data'" class="settings-row"><div><strong>历史日线来源</strong><span>用于走势和网格回测</span></div><select v-model="settingsDraft.historySource" aria-label="历史日线来源"><option value="tencent">腾讯公开行情</option><option value="akshare" disabled>AkShare（待安装）</option><option value="tushare" disabled>Tushare（待配置 Token）</option></select></section>
      <section v-if="settingsTab === 'data'" class="settings-row"><div><strong>选股指标来源</strong><span>用于候选池估值和量价指标</span></div><select v-model="settingsDraft.screenerSource" aria-label="选股指标来源"><option value="tencent">腾讯公开行情</option><option value="akshare" disabled>AkShare（待安装）</option><option value="tushare" disabled>Tushare（待配置 Token）</option></select></section>
      <template v-if="settingsTab === 'connection'"><section v-for="source in dataSources" :key="source.id" class="settings-row"><div><strong>{{ source.name }}</strong><span>{{ source.available ? '连接可用' : source.reason || '暂不可用' }}</span></div><span :class="['setting-status', { 'setting-status-muted': !source.available }]">{{ source.available ? '可用' : source.tushareConfigured ? '待安装' : '未配置' }}</span></section></template>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted } from 'vue';
import { APP_CTX } from '@/modules/views/context';
import { SETTINGS_TABS } from '@/modules/constants';

const ctx = inject(APP_CTX)!;
const {
  hubTab,
  clearReadAlerts,
  alertFilter,
  filteredAlerts,
  markAlertRead,
  settingsDirty,
  settingsLoading,
  saveSettings,
  settingsTab,
  settingsDraft,
  dataSources,
  renderIcons,
} = ctx;

const settingsTabs = SETTINGS_TABS;

onMounted(() => renderIcons());
</script>