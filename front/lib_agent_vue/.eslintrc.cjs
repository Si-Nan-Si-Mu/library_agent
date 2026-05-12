/* eslint-env node */
/**
 * Vue 3 + Vite：不再使用 @vue/cli-plugin-eslint / @babel/eslint-parser。
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  extends: ["eslint:recommended", "plugin:vue/vue3-essential"],
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
  },
  overrides: [
    {
      files: ["*.vue"],
      parser: "vue-eslint-parser",
    },
  ],
};
