import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import ScreenshotEditor from "../components/ScreenshotEditor";

const ORIGINAL = "data:image/png;base64,ORIGINALPIXELS";
const FLATTENED = "data:image/jpeg;base64,FLATTENED";

// jsdom's getContext("2d") returns null, so the editor gets a recorder that logs
// draw calls and style assignments in order — the ordering is what proves an
// annotation is painted onto the original pixels rather than kept as a layer.
function createRecordingContext() {
  const calls = [];
  const ctx = { calls };
  for (const method of [
    "clearRect", "drawImage", "fillRect", "strokeRect", "beginPath",
    "moveTo", "lineTo", "closePath", "stroke", "fill", "fillText",
  ]) {
    ctx[method] = (...args) => calls.push([method, ...args]);
  }
  for (const prop of ["fillStyle", "strokeStyle", "lineWidth", "font"]) {
    let value;
    Object.defineProperty(ctx, prop, {
      get: () => value,
      set: (next) => {
        value = next;
        calls.push([prop, next]);
      },
    });
  }
  return ctx;
}

describe("ScreenshotEditor", () => {
  let ctx;
  let onSave;
  let onCancel;
  let toDataURL;

  beforeEach(() => {
    ctx = createRecordingContext();
    onSave = vi.fn();
    onCancel = vi.fn();
    toDataURL = vi.fn(() => FLATTENED);

    // drawAll, the drag-preview effect and handleSave each call getContext
    // separately; they must all reach the same recorder.
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
    HTMLCanvasElement.prototype.toDataURL = toDataURL;

    // jsdom never loads a data URL, so onload would never fire and the canvas
    // would keep its default dimensions.
    global.Image = class {
      constructor() {
        this.width = 800;
        this.height = 600;
      }
      set src(value) {
        this._src = value;
        this.onload?.();
      }
      get src() {
        return this._src;
      }
    };

    // clientWidth/clientHeight are 0 in jsdom, which makes displayScale negative.
    // 808/608 minus the container's 8px inset is 800x600 against an 800x600
    // image, so displayScale is 1 and canvas coords equal clientX/clientY.
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 808 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 608 });
  });

  afterEach(() => {
    delete HTMLCanvasElement.prototype.getContext;
    delete HTMLCanvasElement.prototype.toDataURL;
    delete HTMLElement.prototype.clientWidth;
    delete HTMLElement.prototype.clientHeight;
    delete global.Image;
    vi.restoreAllMocks();
  });

  const renderEditor = () => {
    const { container } = render(
      <ScreenshotEditor imageDataUrl={ORIGINAL} onSave={onSave} onCancel={onCancel} />
    );
    return container.querySelector("canvas");
  };

  const drag = (canvas, x1, y1, x2, y2) => {
    fireEvent.pointerDown(canvas, { clientX: x1, clientY: y1 });
    fireEvent.pointerMove(canvas, { clientX: x2, clientY: y2 });
    fireEvent.pointerUp(canvas, { clientX: x2, clientY: y2 });
  };

  it("renders the redact, highlight, arrow and text tools and an undo control", () => {
    renderEditor();
    for (const label of ["Redact", "Highlight", "Arrow", "Text", "Undo"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("flattens the redaction into the exported JPEG", () => {
    const canvas = renderEditor();
    drag(canvas, 100, 100, 300, 200);

    // drawAll re-runs on every annotation change; only the save pass is the claim.
    ctx.calls.length = 0;
    fireEvent.click(screen.getByText("Done"));

    const [clear, draw, fill, rect] = ctx.calls;
    expect(clear).toEqual(["clearRect", 0, 0, 800, 600]);
    expect(draw[0]).toBe("drawImage");
    expect(draw[1].src).toBe(ORIGINAL);
    expect(fill).toEqual(["fillStyle", "rgba(0, 0, 0, 1)"]);
    expect(rect).toEqual(["fillRect", 100, 100, 200, 100]);
    expect(toDataURL).toHaveBeenCalledWith("image/jpeg", 0.85);
  });

  it("draws every committed annotation into the export", () => {
    const canvas = renderEditor();
    drag(canvas, 100, 100, 300, 200);
    drag(canvas, 400, 300, 500, 350);

    ctx.calls.length = 0;
    fireEvent.click(screen.getByText("Done"));

    expect(ctx.calls.filter(([name]) => name === "fillRect")).toEqual([
      ["fillRect", 100, 100, 200, 100],
      ["fillRect", 400, 300, 100, 50],
    ]);
  });

  it("hands back only the flattened data URL", () => {
    const canvas = renderEditor();
    drag(canvas, 100, 100, 300, 200);
    fireEvent.click(screen.getByText("Done"));

    expect(onSave).toHaveBeenCalledOnce();
    expect(onSave.mock.calls[0]).toEqual([FLATTENED]);
    expect(onSave.mock.calls[0][0]).not.toBe(ORIGINAL);
  });

  it("undo removes the annotation from the export", () => {
    const canvas = renderEditor();
    drag(canvas, 100, 100, 300, 200);
    drag(canvas, 400, 300, 500, 350);
    fireEvent.click(screen.getByText("Undo"));

    ctx.calls.length = 0;
    fireEvent.click(screen.getByText("Done"));

    const redactions = ctx.calls.filter(([name]) => name === "fillRect");
    expect(redactions).toEqual([["fillRect", 100, 100, 200, 100]]);
  });
});
