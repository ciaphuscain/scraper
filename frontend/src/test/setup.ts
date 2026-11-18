import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom lacks layout; give elements a size so virtualised lists render rows.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get(this: HTMLElement) { return this.hasAttribute("data-index") ? 40 : 800; } });
Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 1000 });
HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement) {
  // Virtualised rows are small; containers are large.
  const h = this.hasAttribute("data-index") ? 40 : 800;
  return { width: 1000, height: h, top: 0, left: 0, bottom: h, right: 1000, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
};
HTMLElement.prototype.scrollTo = function () {} as typeof HTMLElement.prototype.scrollTo;
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get(this: HTMLElement) { return this.hasAttribute("data-index") ? 40 : 800; } });
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1000 });
