import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import './styles.css';

// 全局注册视图组件（App.vue 模板使用 <view-overview> 等 kebab-case 标签）
import ViewOverview from './views/ViewOverview.vue';
import ViewScreener from './views/ViewScreener.vue';
import ViewStockDetail from './views/ViewStockDetail.vue';
import ViewGrid from './views/ViewGrid.vue';
import ViewPlans from './views/ViewPlans.vue';
import ViewMonitor from './views/ViewMonitor.vue';
import ViewSettings from './views/ViewSettings.vue';

const app = createApp(App);
app.use(createPinia());
app.component('view-overview', ViewOverview);
app.component('view-screener', ViewScreener);
app.component('view-stock-detail', ViewStockDetail);
app.component('view-grid', ViewGrid);
app.component('view-plans', ViewPlans);
app.component('view-monitor', ViewMonitor);
app.component('view-settings', ViewSettings);
app.mount('#app');
