// 组件化共享上下文键（P3-1 方案 B）
// 根组件通过 provide(APP_CTX, {...}) 暴露共享状态与函数，视图组件 inject 所需部分。
export const APP_CTX = Symbol('atlas.app.context');
