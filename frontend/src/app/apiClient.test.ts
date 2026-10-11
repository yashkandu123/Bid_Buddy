import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "./apiClient";

describe("resolveApiBaseUrl", () => {
  it("uses the direct FastAPI URL for local Vite development", () => {
    expect(resolveApiBaseUrl(undefined, true)).toBe("http://127.0.0.1:8000");
  });

  it("uses the same-origin API prefix for production", () => {
    expect(resolveApiBaseUrl(undefined, false)).toBe("/api");
  });

  it("honors and normalizes an explicit deployment URL", () => {
    expect(resolveApiBaseUrl(" https://example.test/api/ ", false)).toBe("https://example.test/api");
  });
});
