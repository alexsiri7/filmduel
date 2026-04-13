import { useCallback, useEffect, useRef, useState } from "react";
import { EyeOff, Highlighter, MoveRight, Type, Undo2, Check, X } from "lucide-react";

const TOOLS = [
  { id: "redact", label: "Redact", icon: EyeOff },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "arrow", label: "Arrow", icon: MoveRight },
  { id: "text", label: "Text", icon: Type },
];

export default function ScreenshotEditor({ imageDataUrl, onSave, onCancel }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const imageRef = useRef(null);
  const textInputRef = useRef(null);
  const textInputCreatedAt = useRef(0);

  const [tool, setTool] = useState("redact");
  const [annotations, setAnnotations] = useState([]);
  const [drawing, setDrawing] = useState(false);
  const [startPos, setStartPos] = useState(null);
  const [currentPos, setCurrentPos] = useState(null);
  const [textInput, setTextInput] = useState(null);
  const [textValue, setTextValue] = useState("");
  const [displayScale, setDisplayScale] = useState(1);

  const toCanvasCoords = useCallback(
    (e) => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      return {
        x: (e.clientX - rect.left) / displayScale,
        y: (e.clientY - rect.top) / displayScale,
      };
    },
    [displayScale]
  );

  const drawAll = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);

    for (const ann of annotations) {
      drawAnnotation(ctx, ann);
    }
  }, [annotations]);

  const drawAnnotation = (ctx, ann) => {
    const x = Math.min(ann.startX, ann.endX);
    const y = Math.min(ann.startY, ann.endY);
    const w = Math.abs(ann.endX - ann.startX);
    const h = Math.abs(ann.endY - ann.startY);

    switch (ann.tool) {
      case "redact":
        ctx.fillStyle = "rgba(0, 0, 0, 1)";
        ctx.fillRect(x, y, w, h);
        break;
      case "highlight":
        ctx.fillStyle = "rgba(255, 255, 0, 0.35)";
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = "rgba(255, 255, 0, 0.8)";
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, w, h);
        break;
      case "arrow": {
        const dx = ann.endX - ann.startX;
        const dy = ann.endY - ann.startY;
        const angle = Math.atan2(dy, dx);
        const len = Math.sqrt(dx * dx + dy * dy);
        const headLen = Math.min(20, len * 0.3);

        ctx.strokeStyle = "rgba(220, 38, 38, 1)";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(ann.startX, ann.startY);
        ctx.lineTo(ann.endX, ann.endY);
        ctx.stroke();

        ctx.fillStyle = "rgba(220, 38, 38, 1)";
        ctx.beginPath();
        ctx.moveTo(ann.endX, ann.endY);
        ctx.lineTo(
          ann.endX - headLen * Math.cos(angle - Math.PI / 6),
          ann.endY - headLen * Math.sin(angle - Math.PI / 6)
        );
        ctx.lineTo(
          ann.endX - headLen * Math.cos(angle + Math.PI / 6),
          ann.endY - headLen * Math.sin(angle + Math.PI / 6)
        );
        ctx.closePath();
        ctx.fill();
        break;
      }
      case "text":
        ctx.font = "bold 18px sans-serif";
        ctx.fillStyle = "rgba(220, 38, 38, 1)";
        ctx.fillText(ann.text, ann.startX, ann.startY);
        break;
    }
  };

  // Load image and set canvas dimensions
  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;

      canvas.width = img.width;
      canvas.height = img.height;

      const containerW = container.clientWidth - 8;
      const containerH = container.clientHeight - 8;
      const scale = Math.min(containerW / img.width, containerH / img.height, 1);
      setDisplayScale(scale);

      drawAll();
    };
    img.src = imageDataUrl;
  }, [imageDataUrl]);

  // Redraw when annotations change
  useEffect(() => {
    drawAll();
  }, [drawAll]);

  // Draw preview while dragging
  useEffect(() => {
    if (!drawing || !startPos || !currentPos) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    drawAll();
    drawAnnotation(ctx, {
      tool,
      startX: startPos.x,
      startY: startPos.y,
      endX: currentPos.x,
      endY: currentPos.y,
    });
  }, [drawing, startPos, currentPos, tool, drawAll]);

  // Focus text input when created
  useEffect(() => {
    if (textInput && textInputRef.current) {
      textInputRef.current.focus();
    }
  }, [textInput]);

  const handlePointerDown = useCallback(
    (e) => {
      const pos = toCanvasCoords(e);
      if (tool === "text") {
        textInputCreatedAt.current = Date.now();
        setTextInput(pos);
        setTextValue("");
        return;
      }
      setDrawing(true);
      setStartPos(pos);
      setCurrentPos(pos);
    },
    [tool, toCanvasCoords]
  );

  const handlePointerMove = useCallback(
    (e) => {
      if (!drawing) return;
      setCurrentPos(toCanvasCoords(e));
    },
    [drawing, toCanvasCoords]
  );

  const handlePointerUp = useCallback(() => {
    if (!drawing || !startPos || !currentPos) return;
    setDrawing(false);

    const dx = Math.abs(currentPos.x - startPos.x);
    const dy = Math.abs(currentPos.y - startPos.y);
    if (dx < 3 && dy < 3) return;

    setAnnotations((prev) => [
      ...prev,
      {
        tool,
        startX: startPos.x,
        startY: startPos.y,
        endX: currentPos.x,
        endY: currentPos.y,
      },
    ]);
    setStartPos(null);
    setCurrentPos(null);
  }, [drawing, startPos, currentPos, tool]);

  const commitText = useCallback(() => {
    if (textValue.trim() && textInput) {
      setAnnotations((prev) => [
        ...prev,
        {
          tool: "text",
          startX: textInput.x,
          startY: textInput.y,
          endX: textInput.x,
          endY: textInput.y,
          text: textValue,
        },
      ]);
    }
    setTextInput(null);
    setTextValue("");
  }, [textValue, textInput]);

  const handleTextBlur = useCallback(() => {
    // Prevent blur race when text input was just created
    if (Date.now() - textInputCreatedAt.current < 200) return;
    commitText();
  }, [commitText]);

  const handleTextKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commitText();
      } else if (e.key === "Escape") {
        setTextInput(null);
        setTextValue("");
      }
    },
    [commitText]
  );

  const handleUndo = () => {
    setAnnotations((prev) => prev.slice(0, -1));
  };

  const handleSave = () => {
    // Commit any pending text
    if (textInput && textValue.trim()) {
      commitText();
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawAll();
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    onSave(dataUrl);
  };

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-[#0F0E0D]">
      {/* Toolbar */}
      <div className="flex items-center gap-2 p-3 bg-[#1d1b1a] border-b border-[#F5F0E8]/10">
        {TOOLS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTool(t.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-headline font-bold uppercase tracking-wider transition-colors ${
                tool === t.id
                  ? "bg-[#E8A020] text-[#0F0E0D]"
                  : "text-[#F5F0E8]/60 hover:text-[#F5F0E8]"
              }`}
            >
              <Icon size={14} />
              {t.label}
            </button>
          );
        })}

        <div className="flex-1" />

        <button
          onClick={handleUndo}
          disabled={annotations.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-headline font-bold uppercase tracking-wider text-[#F5F0E8]/60 hover:text-[#F5F0E8] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <Undo2 size={14} />
          Undo
        </button>

        <button
          onClick={handleSave}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-headline font-bold uppercase tracking-wider bg-[#E8A020] text-[#0F0E0D] hover:bg-[#E8A020]/80 transition-colors"
        >
          <Check size={14} />
          Done
        </button>

        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-headline font-bold uppercase tracking-wider text-[#F5F0E8]/60 hover:text-[#F5F0E8] transition-colors"
        >
          <X size={14} />
          Cancel
        </button>
      </div>

      {/* Canvas area */}
      <div ref={containerRef} className="flex-1 flex items-center justify-center overflow-hidden p-1">
        <div className="relative">
          <canvas
            ref={canvasRef}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            className="cursor-crosshair"
            style={{
              width: canvasRef.current ? canvasRef.current.width * displayScale : "auto",
              height: canvasRef.current ? canvasRef.current.height * displayScale : "auto",
            }}
          />
          {textInput && (
            <input
              ref={textInputRef}
              type="text"
              value={textValue}
              onChange={(e) => setTextValue(e.target.value)}
              onBlur={handleTextBlur}
              onKeyDown={handleTextKeyDown}
              className="absolute bg-transparent text-red-600 font-bold text-lg outline-none border-b border-red-600"
              style={{
                left: textInput.x * displayScale,
                top: textInput.y * displayScale - 20,
                minWidth: 100,
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
