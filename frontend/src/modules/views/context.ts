import type { InjectionKey } from 'vue';

// 全局注入上下文（由 App.vue 通过 appOptions.setup() 提供）
// 视图组件通过 inject(APP_CTX) 获取全部状态与函数
export const APP_CTX: InjectionKey<Record<string, any>> = Symbol('atlas.app.context');
