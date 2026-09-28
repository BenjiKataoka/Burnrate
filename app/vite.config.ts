import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const page = (name: string): string => fileURLToPath(new URL(name, import.meta.url));

export default defineConfig({
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: {
    target: "safari16",
    rollupOptions: {
      input: {
        dashboard: page("index.html"),
        widget: page("widget.html"),
      },
    },
  },
});
