import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    // Two projects: the data layer and API routes run in Node; components
    // render in jsdom with Testing Library. Both inherit this file's config.
    projects: [
      {
        extends: true,
        test: {
          name: "node",
          environment: "node",
          include: ["src/lib/**/*.test.ts", "src/app/api/**/*.test.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "jsdom",
          environment: "jsdom",
          include: ["src/components/**/*.test.tsx"],
          setupFiles: ["./src/test/setup.ts"],
        },
      },
    ],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/app/layout.tsx",
        "src/app/error.tsx",
        "src/app/**/page.tsx", // thin server wrappers around tested components
        // Vendored shadcn/ui primitives; exercised through the components that use them.
        "src/components/ui/**",
      ],
    },
  },
});
