// eslint.config.js — ESLint 9 flat config（TS + Vue SFC 全覆盖）
// Phase 6：引入 typescript-eslint 推荐规则集与 eslint-plugin-vue，覆盖 frontend/src 下 .ts / .vue。
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import vue from 'eslint-plugin-vue';

export default [
  { ignores: ['node_modules/**', 'frontend/vendor/**', 'frontend/dist/**', 'tests/frontend/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['frontend/src/**/*.{ts,vue}'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
      globals: { ...globals.browser },
    },
    rules: {
      // 后端返回的行情字段常含动态结构，显式 any 是既有约定
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
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
    files: ['server.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'commonjs', globals: globals.node },
  },
];
