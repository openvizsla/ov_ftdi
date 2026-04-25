// Typed wrappers over the ovweb REST + WebSocket API.

export interface SessionSummary {
  id: number;
  started_at: string;
  ended_at: string | null;
  speed: string;
  status: string;
  notes: string | null;
}

export interface Transfer {
  ts_ns: number;
  device_addr: number;
  ep_addr: number;
  direction: string;
  type: string;
  status: string;
  length: number;
  setup_hex: string | null;
  data_hex: string | null;
}

export interface DeviceInfo {
  bus: number;
  address: number;
  port_path: string;
  serial: string | null;
  vid: number;
  pid: number;
  description: string;
}

export interface EndpointStat {
  key: string;
  device_addr: number;
  ep_addr: number;
  direction: string;
  type: string;
  count: number;
  bytes: number;
  acks: number;
  naks: number;
  stalls: number;
  nyets: number;
  incompletes: number;
  last_ts_ns: number;
  last_data_hex: string | null;
  status_run_kind: string;
  status_run_len: number;
}

export type LiveEventKind =
  | 'new_endpoint'
  | 'control_transfer'
  | 'payload_change'
  | 'status_flip'
  | 'speed_locked'
  | 'speed_lost'
  | 'overflow';

export interface LiveEvent {
  type: 'event';
  session_id: number;
  kind: LiveEventKind;
  ts_ns?: number;
  key?: string;
  [extra: string]: unknown;
}

export interface HelloMessage {
  type: 'hello';
  session_id: number;
  channels_default: string[];
  snapshot: { endpoints: EndpointStat[] };
}

export interface EndpointUpdateMessage {
  type: 'endpoint_update';
  session_id: number;
  updates: EndpointStat[];
}

export interface TransferMessage {
  type: 'transfer';
  session_id: number;
  transfer: Transfer;
}

export interface EndMessage {
  type: 'end';
  session_id: number;
  packets: number;
  transfers: number;
}

export interface ErrorMessage {
  type: 'error';
  error: string;
}

export type LiveMessage =
  | HelloMessage
  | EndpointUpdateMessage
  | TransferMessage
  | LiveEvent
  | EndMessage
  | ErrorMessage;

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch('/api/sessions');
  if (!r.ok) throw new Error(`list sessions failed: ${r.status}`);
  return r.json();
}

export async function fetchDevices(): Promise<{ devices: DeviceInfo[]; selected_policy: string }> {
  const r = await fetch('/api/devices');
  if (!r.ok) throw new Error(`list devices failed: ${r.status}`);
  return r.json();
}

export async function startSession(
  speed: string,
  notes?: string,
  deviceSerial?: string | null,
): Promise<{ session_id: number; speed: string }> {
  const body: Record<string, unknown> = { speed };
  if (notes) body.notes = notes;
  if (deviceSerial) body.device_serial = deviceSerial;
  const r = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`start failed: ${r.status} ${await r.text()}`);
  return r.json();
}

export async function stopSession(sessionId: number): Promise<{ session_id: number; packets: number; transfers: number }> {
  const r = await fetch(`/api/sessions/${sessionId}/stop`, { method: 'POST' });
  if (!r.ok) throw new Error(`stop failed: ${r.status} ${await r.text()}`);
  return r.json();
}

export function openLive(
  sessionId: number,
  onMsg: (msg: LiveMessage) => void,
  onClose?: () => void,
): WebSocket {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/api/sessions/${sessionId}/live`);
  ws.onmessage = (ev) => {
    try {
      onMsg(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  };
  ws.onclose = () => {
    onClose?.();
  };
  return ws;
}

export function subscribeChannels(ws: WebSocket, channels: string[]): void {
  if (ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'subscribe', channels }));
}
