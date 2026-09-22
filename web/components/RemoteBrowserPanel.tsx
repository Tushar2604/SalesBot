"use client";

/**
 * Live view of a real, human-driven Chromium session signing into LinkedIn.
 *
 * Frames arrive as JPEG blobs and get drawn onto a canvas; clicks/keystrokes
 * on that canvas are relayed back over the same socket so the actual remote
 * page receives them (see lib/remoteBrowserSocket.ts for the wire format).
 * No auto-reconnect on a dropped connection — a session lost mid-login should
 * surface as "try again", never silently relaunch a second browser under the
 * same account while the first might still be live server-side.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, linkedinApi } from "@/lib/api";
import { RemoteBrowserSocket, type StatusMessage } from "@/lib/remoteBrowserSocket";

type Phase = "starting" | "launching" | "live" | "success" | "closed" | "error";

export function RemoteBrowserPanel({
  workspaceId,
  label,
  timezone,
  proxyId,
  onClose,
  onConnected,
}: {
  workspaceId: string;
  label: string;
  timezone: string;
  proxyId: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const socketRef = useRef<RemoteBrowserSocket | null>(null);
  const naturalSizeRef = useRef<{ width: number; height: number } | null>(null);

  const [phase, setPhase] = useState<Phase>("starting");
  const [detail, setDetail] = useState("Starting a browser session…");

  const start = useCallback(async () => {
    setPhase("starting");
    setDetail("Starting a browser session…");
    try {
      const account = await linkedinApi.createRemoteAccount(workspaceId, {
        label,
        timezone,
        proxy_id: proxyId || null,
      });
      const { ws_url } = await linkedinApi.startRemoteSession(workspaceId, account.id);

      const socket = new RemoteBrowserSocket(ws_url, {
        onFrame: (blob) => void drawFrame(blob),
        onStatus: (status) => applyStatus(status),
        onClose: (code, reason) => {
          setPhase((prev) => (prev === "success" ? prev : "closed"));
          const fallback =
            code === 1000
              ? "Session ended."
              : code === 4003
                ? "Could not start Chromium. Retry in a moment."
                : code === 1006
                ? "The browser session dropped before Chromium started. Retry in a moment."
                : `Connection closed (${code}).`;
          setDetail(reason || fallback);
        },
      });
      socketRef.current = socket;
      setPhase("launching");
      setDetail("Opening a browser through this account's connection…");
    } catch (err) {
      setPhase("error");
      setDetail(err instanceof ApiError ? err.message : "Could not start a remote browser session");
    }
  }, [workspaceId, label, timezone, proxyId]);

  useEffect(() => {
    void start();
    return () => socketRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyStatus(status: StatusMessage) {
    if (status.state === "live") {
      setPhase("live");
      setDetail(status.detail || "Sign in on the page below.");
    } else if (status.state === "login_success") {
      setPhase("success");
      setDetail(status.detail || "Signed in — finishing setup…");
      onConnected();
    } else if (status.state === "session_closed") {
      setPhase("closed");
      setDetail(status.detail || "Session ended.");
    } else if (status.state === "error") {
      setPhase("error");
      setDetail(status.detail || "Something went wrong.");
    }
  }

  async function drawFrame(blob: Blob) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const bitmap = await createImageBitmap(blob);
    naturalSizeRef.current = { width: bitmap.width, height: bitmap.height };
    if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
    }
    const ctx = canvas.getContext("2d");
    ctx?.drawImage(bitmap, 0, 0);
    bitmap.close();
  }

  function toRemoteCoords(e: React.MouseEvent<HTMLCanvasElement>): { x: number; y: number } {
    const canvas = canvasRef.current;
    const natural = naturalSizeRef.current;
    if (!canvas || !natural) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = natural.width / rect.width;
    const scaleY = natural.height / rect.height;
    return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
  }

  function onMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    canvasRef.current?.focus();
    const { x, y } = toRemoteCoords(e);
    socketRef.current?.sendMouse({ event: "mousedown", x, y });
  }
  function onMouseUp(e: React.MouseEvent<HTMLCanvasElement>) {
    const { x, y } = toRemoteCoords(e);
    socketRef.current?.sendMouse({ event: "mouseup", x, y });
  }
  function onMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const { x, y } = toRemoteCoords(e);
    socketRef.current?.sendMouse({ event: "mousemove", x, y });
  }
  function onWheel(e: React.WheelEvent<HTMLCanvasElement>) {
    const { x, y } = toRemoteCoords(e);
    socketRef.current?.sendMouse({ event: "wheel", x, y, deltaY: e.deltaY });
  }
  function onKeyDown(e: React.KeyboardEvent<HTMLCanvasElement>) {
    e.preventDefault();
    socketRef.current?.sendKey({
      event: "keydown",
      key: e.key,
      code: e.code,
      windowsVirtualKeyCode: e.keyCode,
      text: e.key.length === 1 ? e.key : "",
    });
  }
  function onKeyUp(e: React.KeyboardEvent<HTMLCanvasElement>) {
    e.preventDefault();
    socketRef.current?.sendKey({
      event: "keyup",
      key: e.key,
      code: e.code,
      windowsVirtualKeyCode: e.keyCode,
    });
  }

  function close() {
    socketRef.current?.close();
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      // Rendered nested inside ConnectAccountDialog's own click-to-close
      // overlay — without this, any click here (including just interacting
      // with the live LinkedIn page) would bubble up and close that dialog
      // out from under this panel.
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Sign in with browser</h2>
            <p className="mt-0.5 text-sm text-slate-500">{detail}</p>
          </div>
          <button onClick={close} className="text-slate-500 hover:text-slate-700" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="flex min-h-[300px] flex-1 items-center justify-center bg-slate-950 p-2">
          {phase === "starting" || phase === "launching" ? (
            <p className="text-sm text-slate-300">{detail}</p>
          ) : phase === "success" ? (
            <p className="text-sm font-medium text-emerald-400">✓ Signed in — you can close this.</p>
          ) : phase === "closed" || phase === "error" ? (
            <p className="max-w-sm text-center text-sm text-slate-300">{detail}</p>
          ) : (
            <canvas
              ref={canvasRef}
              tabIndex={0}
              className="max-h-[70vh] max-w-full cursor-default outline-none"
              onMouseDown={onMouseDown}
              onMouseUp={onMouseUp}
              onMouseMove={onMouseMove}
              onWheel={onWheel}
              onKeyDown={onKeyDown}
              onKeyUp={onKeyUp}
            />
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-slate-200 px-5 py-4">
          {(phase === "closed" || phase === "error") && (
            <button className="btn-primary" onClick={() => void start()}>
              Retry
            </button>
          )}
          <button className="btn-ghost" onClick={close}>
            {phase === "success" ? "Done" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
