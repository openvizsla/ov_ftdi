<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    listSessions, startSession, stopSession, openLive, subscribeChannels, fetchDevices,
    type SessionSummary, type Transfer, type DeviceInfo, type EndpointStat,
    type LiveEvent, type LiveMessage,
  } from './api';

  let sessions: SessionSummary[] = [];
  let devices: DeviceInfo[] = [];
  let selectedSerial: string | null = null;
  let deviceError: string | null = null;

  let speed: 'ls' | 'fs' | 'hs' = 'ls';
  let notes = '';
  let activeId: number | null = null;
  let lockedSpeed: string | null = null;
  let status: 'idle' | 'starting' | 'running' | 'stopping' = 'idle';
  let error: string | null = null;

  // Endpoint summary: keyed live table.
  let endpoints = new Map<string, EndpointStat>();
  // Filtered event stream: newest first, bounded.
  let events: LiveEvent[] = [];
  const MAX_EVENTS = 500;
  // Raw firehose: opt-in; only populated when the <details> is open.
  let firehose: Transfer[] = [];
  const MAX_FIRE = 500;
  let firehoseOpen = false;

  let ws: WebSocket | null = null;

  async function refreshSessions() {
    try { sessions = await listSessions(); } catch (e: any) { error = String(e); }
  }

  async function rescan() {
    deviceError = null;
    try {
      const r = await fetchDevices();
      devices = r.devices;
      // Auto-select when exactly one. Otherwise keep whatever the user picked
      // if it's still in the list; else clear.
      if (devices.length === 1) {
        selectedSerial = devices[0].serial;
      } else if (selectedSerial && !devices.find(d => d.serial === selectedSerial)) {
        selectedSerial = null;
      }
    } catch (e: any) {
      devices = [];
      deviceError = String(e);
    }
  }

  function describeDevice(d: DeviceInfo): string {
    const ser = d.serial ? `serial ${d.serial}` : 'serial ?';
    return `${d.description} · bus ${d.bus} port ${d.port_path || '?'} · ${ser}`;
  }

  function handleLive(msg: LiveMessage) {
    switch (msg.type) {
      case 'hello':
        // Prime endpoint table with the initial snapshot (empty on fresh
        // capture, populated if we reconnected mid-session).
        endpoints = new Map(msg.snapshot.endpoints.map(e => [e.key, e]));
        break;
      case 'endpoint_update': {
        // Replace dirty rows in place. Rebuild the Map so Svelte's reactivity
        // fires on the {#each} keyed block.
        const next = new Map(endpoints);
        for (const u of msg.updates) next.set(u.key, u);
        endpoints = next;
        break;
      }
      case 'event': {
        events = [msg, ...events].slice(0, MAX_EVENTS);
        break;
      }
      case 'transfer':
        firehose = [...firehose.slice(-MAX_FIRE + 1), msg.transfer];
        break;
      case 'end':
        ws?.close();
        ws = null;
        break;
      case 'error':
        error = `live feed: ${msg.error}`;
        break;
    }
  }

  async function start() {
    error = null; status = 'starting';
    try {
      const r = await startSession(speed, notes || undefined, selectedSerial);
      activeId = r.session_id;
      lockedSpeed = r.speed;
      endpoints = new Map();
      events = [];
      firehose = [];
      ws = openLive(r.session_id, handleLive, () => { ws = null; });
      status = 'running';
      await refreshSessions();
    } catch (e: any) {
      error = String(e); status = 'idle';
    }
  }

  async function stop() {
    if (activeId == null) return;
    status = 'stopping';
    try {
      await stopSession(activeId);
    } catch (e: any) {
      error = String(e);
    }
    ws?.close(); ws = null;
    activeId = null; lockedSpeed = null;
    status = 'idle';
    await refreshSessions();
  }

  function toggleFirehose(ev: Event) {
    const d = ev.currentTarget as HTMLDetailsElement;
    firehoseOpen = d.open;
    if (!ws) return;
    subscribeChannels(ws, firehoseOpen
      ? ['summary', 'events', 'firehose']
      : ['summary', 'events']);
    if (!firehoseOpen) firehose = [];
  }

  function formatHex(hex: string | null, cap = 32): string {
    if (!hex) return '';
    if (hex.length <= cap) return hex;
    return hex.slice(0, cap) + '…';
  }

  function formatEvent(e: LiveEvent): string {
    switch (e.kind) {
      case 'new_endpoint':
        return `new endpoint ${e.key} · ${e.type} ${e.direction}`;
      case 'control_transfer':
        return `control ${e.key} · setup=${formatHex((e.setup_hex as string) || null)} · ${e.status}`;
      case 'payload_change':
        return `payload ${e.key} ${e.first_seen ? '(first)' : 'changed'} · ${formatHex((e.data_hex as string) || null, 48)}`;
      case 'status_flip':
        return `${e.from}→${e.to} on ${e.key} (prev run ${e.prev_run_len})`;
      case 'speed_locked':
        return `speed locked: ${e.speed}`;
      case 'speed_lost':
        return 'speed lost';
      case 'overflow':
        return `overflow +${e.delta} (total ${e.count})`;
      default:
        return `${e.kind} ${JSON.stringify(e)}`;
    }
  }

  $: endpointList = [...endpoints.values()].sort((a, b) => {
    if (a.device_addr !== b.device_addr) return a.device_addr - b.device_addr;
    return a.ep_addr - b.ep_addr;
  });

  $: canStart = status === 'idle' && devices.length >= 1;

  onMount(async () => {
    await rescan();
    await refreshSessions();
  });
  onDestroy(() => ws?.close());
</script>

<main>
  <header>
    <h1>ovweb <span class="sub">OpenVizsla 3 · session recorder</span></h1>
  </header>

  {#if error}
    <div class="error">{error} <button on:click={() => (error = null)}>×</button></div>
  {/if}

  <section class="controls">
    <label>Device
      <select bind:value={selectedSerial} disabled={status !== 'idle' || devices.length === 0}>
        {#if devices.length === 0}
          <option value={null}>no OpenVizsla detected</option>
        {:else}
          {#each devices as d (d.serial ?? `${d.bus}.${d.port_path}`)}
            <option value={d.serial}>{describeDevice(d)}</option>
          {/each}
        {/if}
      </select>
    </label>
    <button class="secondary" on:click={rescan} disabled={status !== 'idle'}>Rescan</button>

    <label>Speed
      <select bind:value={speed} disabled={status !== 'idle'}>
        <option value="ls">Low · 1.5 Mbps</option>
        <option value="fs">Full · 12 Mbps</option>
        <option value="hs">High · 480 Mbps</option>
      </select>
    </label>
    <label>Notes
      <input type="text" bind:value={notes} placeholder="optional" disabled={status !== 'idle'} />
    </label>

    {#if status === 'idle'}
      <button class="primary" on:click={start} disabled={!canStart}>Start capture</button>
    {:else if status === 'running'}
      <button class="danger" on:click={stop}>Stop capture</button>
    {:else}
      <button disabled>{status}…</button>
    {/if}
    {#if activeId != null}
      <span class="badge">session #{activeId} · locked at {lockedSpeed}</span>
    {/if}
  </section>

  {#if devices.length > 1}
    <div class="warn">
      {devices.length} OpenVizsla boards detected. libopenvizsla 4.6 opens the
      first match; device_serial is recorded on the session but not honored
      for selection until Phase 4.7.
    </div>
  {:else if devices.length === 0 && !deviceError}
    <div class="muted small">
      No OpenVizsla detected. Plug one in and click Rescan.
    </div>
  {/if}
  {#if deviceError}
    <div class="error small">{deviceError}</div>
  {/if}

  <section class="panel">
    <h2>Endpoints {endpointList.length ? `(${endpointList.length})` : ''}</h2>
    {#if activeId == null}
      <p class="muted">No active capture.</p>
    {:else if endpointList.length === 0}
      <p class="muted">Waiting for first transfer…</p>
    {:else}
      <table>
        <thead>
          <tr>
            <th>ep</th><th>type</th><th>dir</th>
            <th class="num">count</th>
            <th class="num">bytes</th>
            <th class="num">ack</th>
            <th class="num">nak</th>
            <th class="num">stall</th>
            <th>run</th>
            <th>last payload</th>
          </tr>
        </thead>
        <tbody>
          {#each endpointList as e (e.key)}
            <tr>
              <td>{e.key}</td>
              <td>{e.type}</td>
              <td>{e.direction}</td>
              <td class="num">{e.count}</td>
              <td class="num">{e.bytes}</td>
              <td class="num">{e.acks}</td>
              <td class="num">{e.naks}</td>
              <td class="num {e.stalls ? 'bad' : ''}">{e.stalls}</td>
              <td>{e.status_run_kind}×{e.status_run_len}</td>
              <td class="hex">{formatHex(e.last_data_hex)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </section>

  <section class="panel">
    <h2>Events {events.length ? `(${events.length})` : ''}</h2>
    {#if activeId == null}
      <p class="muted">No active capture.</p>
    {:else if events.length === 0}
      <p class="muted">Filtered stream — no notable events yet.</p>
    {:else}
      <ul class="events">
        {#each events as e (e.ts_ns !== undefined ? `${e.ts_ns}-${e.kind}-${e.key ?? ''}` : `${e.kind}-${events.indexOf(e)}`)}
          <li class={e.kind}>
            <span class="ek">{e.kind}</span>
            {formatEvent(e)}
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="panel">
    <details on:toggle={toggleFirehose}>
      <summary>
        <h2 style="display:inline">Raw firehose {firehoseOpen ? `(${firehose.length})` : '— expand to subscribe'}</h2>
      </summary>
      {#if firehoseOpen}
        <table>
          <thead>
            <tr>
              <th>t (ns)</th><th>ep</th><th>dir</th><th>status</th>
              <th class="num">len</th><th>data</th>
            </tr>
          </thead>
          <tbody>
            {#each firehose as t (t.ts_ns)}
              <tr class={t.status}>
                <td class="num">{t.ts_ns}</td>
                <td>{t.device_addr}.{t.ep_addr}</td>
                <td>{t.direction}</td>
                <td>{t.status}</td>
                <td class="num">{t.length}</td>
                <td class="hex">{formatHex(t.data_hex)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </details>
  </section>

  <section class="panel">
    <h2>Sessions</h2>
    <table>
      <thead>
        <tr><th>id</th><th>started</th><th>ended</th><th>speed</th><th>status</th></tr>
      </thead>
      <tbody>
        {#each sessions as s (s.id)}
          <tr>
            <td>#{s.id}</td>
            <td class="num">{s.started_at.replace('T',' ').slice(0,19)}</td>
            <td class="num">{s.ended_at ? s.ended_at.replace('T',' ').slice(0,19) : '—'}</td>
            <td>{s.speed}</td>
            <td>{s.status}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>
</main>

<style>
  :global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0e1013; color: #d6dde6; }
  main { max-width: 1200px; margin: 0 auto; padding: 1rem 1.5rem 3rem; }
  h1 { margin: 0.2rem 0 1rem; font-size: 1.4rem; font-weight: 600; }
  h1 .sub { color: #7d8593; font-weight: 400; font-size: 0.9rem; margin-left: 0.5rem; }
  h2 { font-size: 1rem; margin: 0 0 0.5rem; color: #a9b3c2; font-weight: 500; }
  .controls { display: flex; align-items: end; gap: 1rem; flex-wrap: wrap;
              background: #161a21; padding: 0.8rem 1rem; border-radius: 8px; margin-bottom: 1rem; }
  .controls label { display: flex; flex-direction: column; font-size: 0.8rem; color: #7d8593; gap: 0.25rem; }
  select, input, button { background: #0e1013; color: #d6dde6; border: 1px solid #2a3140;
                          padding: 0.35rem 0.6rem; border-radius: 4px; font: inherit; }
  button.primary { background: #2c5fdb; border-color: #2c5fdb; color: white; cursor: pointer; }
  button.danger { background: #c2414e; border-color: #c2414e; color: white; cursor: pointer; }
  button.secondary { cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: default; }
  .badge { background: #1f2633; border-radius: 4px; padding: 0.3rem 0.6rem; font-size: 0.85rem; }
  .error { background: #3a1a1f; color: #ffc0c0; padding: 0.5rem 0.75rem; margin-bottom: 1rem;
           border-radius: 4px; display: flex; justify-content: space-between; }
  .error.small { font-size: 0.85rem; padding: 0.3rem 0.6rem; }
  .error button { background: transparent; border: 0; color: #ffc0c0; cursor: pointer; }
  .warn { background: #2d2517; color: #ffd891; padding: 0.5rem 0.75rem; margin-bottom: 1rem;
          border-radius: 4px; font-size: 0.85rem; }
  .panel { background: #161a21; border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 0.8rem; overflow: auto; max-height: 60vh; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th, td { text-align: left; padding: 0.25rem 0.5rem; border-bottom: 1px solid #20252f; }
  th { color: #7d8593; font-weight: 500; position: sticky; top: 0; background: #161a21; }
  .num { font-variant-numeric: tabular-nums; color: #a9b3c2; text-align: right; }
  .hex { font-family: ui-monospace, monospace; color: #6fa3d4; }
  .muted { color: #7d8593; }
  .muted.small { font-size: 0.85rem; margin: 0.3rem 0; }
  .bad { color: #ff9090; font-weight: 600; }
  tr.nak { color: #7d8593; }
  tr.stall { color: #ff9090; }
  tr.incomplete { color: #e0a060; }
  .events { list-style: none; margin: 0; padding: 0; font-size: 0.85rem; }
  .events li { padding: 0.25rem 0.5rem; border-bottom: 1px solid #20252f; }
  .events li.new_endpoint { color: #9fd89f; }
  .events li.control_transfer { color: #c2a7e8; }
  .events li.payload_change { color: #6fa3d4; }
  .events li.status_flip { color: #ffd891; }
  .events li.speed_locked { color: #9fd89f; font-weight: 600; }
  .events li.speed_lost { color: #ff9090; font-weight: 600; }
  .events li.overflow { color: #ff9090; font-weight: 600; }
  .events .ek { display: inline-block; min-width: 9rem; color: #7d8593; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
  details summary { cursor: pointer; padding: 0.25rem 0; }
</style>
