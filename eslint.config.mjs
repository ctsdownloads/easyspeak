// ESLint flat config for the GNOME Shell extension (GJS / ESM).
//
// gnome-shell injects a handful of globals, and the `gi://` / `resource://`
// imports are resolved by gjs only inside the running shell process — so this
// config deliberately stays lightweight: it lints syntax and obvious mistakes
// (undefined names, unused vars) without trying to resolve modules.
export default [
  {
    files: ["src/extension.js", "src/extension-helpers.js", "src/prefs.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        // Logging / printing builtins provided by GJS.
        log: "readonly",
        logError: "readonly",
        print: "readonly",
        printerr: "readonly",
        // Shell / GJS runtime globals.
        global: "readonly",
        globalThis: "readonly",
        imports: "readonly",
        console: "readonly",
        TextEncoder: "readonly",
        TextDecoder: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": "error",
    },
  },
];
