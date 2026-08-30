// eslint.config.js — ESLint 9 flat config（项目无打包器、无 TS，JS + 全局 Vue）
import js from '@eslint/js';
import globals from 'globals';

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
    files: ['server.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'commonjs', globals: globals.node },
  },
];
