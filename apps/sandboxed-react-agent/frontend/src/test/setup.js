import "@testing-library/jest-dom/vitest";

if (!globalThis.crypto) {
  globalThis.crypto = {
    randomUUID: () => "test-uuid",
  };
}
