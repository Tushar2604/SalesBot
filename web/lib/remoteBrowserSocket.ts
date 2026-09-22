/**
 * Thin WebSocket client for a remote-browser login session.
 *
 * Wire format (must match api/app/linkedin/remote_browser/protocol.py):
 *  - server → client: raw JPEG bytes (screencast frames), or a JSON text
 *    frame `{type: "status", state, detail}`.
 *  - client → server: JSON text frames matching `MouseInput`/`KeyInput` —
 *    field names are snake_case because the backend has no camelCase alias
 *    configured, so this file must send exactly `delta_y`,
 *    `windows_virtual_key_code`, not their camelCase equivalents.
 */

export type StatusState = "launching" | "live" | "login_success" | "session_closed" | "error";

export type StatusMessage = {
  type: "status";
  state: StatusState;
  detail: string;
};

type Listeners = {
  onFrame: (blob: Blob) => void;
  onStatus: (status: StatusMessage) => void;
  onClose: (code: number, reason: string) => void;
};

export class RemoteBrowserSocket {
  private ws: WebSocket;

  constructor(url: string, listeners: Listeners) {
    this.ws = new WebSocket(url);
    this.ws.binaryType = "blob";

    this.ws.onmessage = (event: MessageEvent<Blob | string>) => {
      if (event.data instanceof Blob) {
        listeners.onFrame(event.data);
        return;
      }
      try {
        const parsed = JSON.parse(event.data) as StatusMessage;
        if (parsed.type === "status") listeners.onStatus(parsed);
      } catch {
        // Not a status frame we understand — ignore rather than crash the session.
      }
    };

    this.ws.onclose = (event: CloseEvent) => listeners.onClose(event.code, event.reason);
    this.ws.onerror = () => {
      // onclose always follows; keep this so failed handshakes still notify.
    };
  }

  private send(message: Record<string, unknown>): void {
    if (this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(message));
  }

  sendMouse(input: {
    event: "mousedown" | "mouseup" | "mousemove" | "wheel";
    x: number;
    y: number;
    button?: "left" | "middle" | "right";
    deltaY?: number;
  }): void {
    this.send({
      type: "mouse",
      event: input.event,
      x: input.x,
      y: input.y,
      button: input.button ?? "left",
      delta_y: input.deltaY ?? 0,
    });
  }

  sendKey(input: {
    event: "keydown" | "keyup";
    key: string;
    code: string;
    windowsVirtualKeyCode?: number;
    text?: string;
  }): void {
    this.send({
      type: "key",
      event: input.event,
      key: input.key,
      code: input.code,
      windows_virtual_key_code: input.windowsVirtualKeyCode ?? 0,
      text: input.text ?? "",
    });
  }

  close(): void {
    this.ws.close();
  }
}
