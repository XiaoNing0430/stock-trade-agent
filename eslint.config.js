// eslint.config.js — ESLint 9 flat config（项目无打包器、无 TS，JS + 全局 Vue）
// Phase 6 会补齐 typescript-eslint 类型感知规则；此处仅做最小 TS 解析支持。
import js from '@eslint/js';
import globals from 'globals';
import tsParser from '@typescript-eslint/parser';

export default [
  { ignores: ['node_modules/**', 'frontend/vendor/**', 'frontend/dist/**', 'tests/frontend/**'] },
  js.configs.recommended,
  {
    files: ['frontend/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, Vue: 'readonly' },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-console': 'off',
    },
  },
  {
    files: ['frontend/src/**/*.ts'],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // TS 全局类型（RequestInit 等）由 vue-tsc 校验，eslint 不重复检查
      'no-undef': 'off',
    },
  },
  {
    files: ['server.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'commonjs', globals: globals.node },
  },
];
