import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Integration tests spawn the compiled CLI and TypeScript runners as
    // child processes, so the 5s default times out under CI load.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
