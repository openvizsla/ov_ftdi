<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fly, fade } from 'svelte/transition';
  import {
    listSessions, startSession, stopSession, openLive, subscribeChannels, fetchDevices,
    type SessionSummary, type Transfer, type DeviceInfo, type EndpointStat,
    type LiveEvent, type LiveMessage,
  } from './api';

  // ------ state ------

  let sessions: SessionSummary[] = [];
  let devices: DeviceInfo[] = [];
  let selectedSerial: string | null = null;
  let deviceError: string | null = null;

  type Speed = 'ls' | 'fs' | 'hs';
  const SPEEDS: Speed[] = ['ls', 'fs', 'hs'];
  let speed: Speed = 'ls';
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

  // Session timer.
  let startedAt: number | null = null;
  let now = Date.now();
  let tickHandle: ReturnType<typeof setInterval> | null = null;

  function startTimer() {
    startedAt = Date.now();
    tickHandle = setInterval(() => { now = Date.now(); }, 1000);
  }
  function stopTimer() {
    if (tickHandle) clearInterval(tickHandle);
    tickHandle = null;
    startedAt = null;
  }

  // ------ api glue ------

  async function refreshSessions() {
    try { sessions = await listSessions(); } catch (e: any) { error = String(e); }
  }

  async function rescan() {
    deviceError = null;
    try {
      const r = await fetchDevices();
      devices = r.devices;
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

  function handleLive(msg: LiveMessage) {
    switch (msg.type) {
      case 'hello':
        endpoints = new Map(msg.snapshot.endpoints.map(e => [e.key, e]));
        break;
      case 'endpoint_update': {
        const next = new Map(endpoints);
        for (const u of msg.updates) next.set(u.key, u);
        endpoints = next;
        break;
      }
      case 'event':
        events = [msg, ...events].slice(0, MAX_EVENTS);
        break;
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
      startTimer();
      await refreshSessions();
    } catch (e: any) {
      error = String(e); status = 'idle';
    }
  }

  async function stop() {
    if (activeId == null) return;
    status = 'stopping';
    try { await stopSession(activeId); } catch (e: any) { error = String(e); }
    ws?.close(); ws = null;
    stopTimer();
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

  // ------ formatters ------

  function fmtHex(hex: string | null, cap = 24): string {
    if (!hex) return '';
    const normalized = hex.toLowerCase();
    const grouped = normalized.match(/.{1,2}/g)?.join(' ') ?? normalized;
    if (grouped.length <= cap) return grouped;
    return grouped.slice(0, cap) + ' …';
  }

  function fmtElapsed(ms: number): string {
    const s = Math.floor(ms / 1000);
    const hh = String(Math.floor(s / 3600)).padStart(2, '0');
    const mm = String(Math.floor(s / 60) % 60).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    return `${hh}:${mm}:${ss}`;
  }

  function fmtInt(n: number): string {
    // Tabular separators like 1 024 (thin-space locale-agnostic).
    return n.toLocaleString('en-US').replace(/,/g, ' ');
  }

  function fmtSessionAge(started: string, ended: string | null): string {
    const t0 = Date.parse(started);
    const t1 = ended ? Date.parse(ended) : Date.now();
    const sec = Math.max(0, Math.floor((t1 - t0) / 1000));
    if (sec < 60)   return `${sec}s`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    return `${h}h ${m}m`;
  }

  function formatEvent(e: LiveEvent): string {
    switch (e.kind) {
      case 'new_endpoint':
        return `${e.type} ${e.direction} · ${e.key}`;
      case 'control_transfer':
        return `${e.key} setup=${fmtHex((e.setup_hex as string) || null)} · ${e.status}`;
      case 'payload_change':
        return `${e.key} ${e.first_seen ? '(first)' : '(Δ)'} · ${fmtHex((e.data_hex as string) || null, 42)}`;
      case 'status_flip':
        return `${e.key} · ${e.from} → ${e.to} (after ${e.prev_run_len})`;
      case 'speed_locked':
        return `locked at ${e.speed}`;
      case 'speed_lost':
        return 'speed lost';
      case 'overflow':
        return `+${e.delta} dropped (total ${e.count})`;
      default:
        return `${e.kind}`;
    }
  }

  function describeDevice(d: DeviceInfo): string {
    return d.serial ?? `${d.description} @ bus ${d.bus}.${d.port_path}`;
  }

  // ------ derived state ------

  $: endpointList = [...endpoints.values()].sort((a, b) => {
    if (a.device_addr !== b.device_addr) return a.device_addr - b.device_addr;
    return a.ep_addr - b.ep_addr;
  });

  $: canStart = status === 'idle' && devices.length >= 1;

  $: totalXfers = endpointList.reduce((a, e) => a + e.count, 0);
  $: totalAcks  = endpointList.reduce((a, e) => a + e.acks,  0);
  $: totalNaks  = endpointList.reduce((a, e) => a + e.naks,  0);
  $: totalErrs  = endpointList.reduce((a, e) => a + e.stalls + e.nyets + e.incompletes, 0);

  $: elapsed = startedAt ? fmtElapsed(now - startedAt) : '00:00:00';
  $: activeDevice = devices.find(d => d.serial === selectedSerial) ?? devices[0] ?? null;

  // ------ lifecycle ------

  onMount(async () => {
    await rescan();
    await refreshSessions();
  });
  onDestroy(() => { ws?.close(); stopTimer(); });
</script>

<div class="shell">
  <!-- ░░░░░░░░░░░░░░░░░░░░░░░  MASTHEAD  ░░░░░░░░░░░░░░░░░░░░░░░ -->
  <header class="masthead">
    <div class="mast-l">
      <span class="brand">ovweb</span>
      <span class="rule">━━</span>
      <span class="dateline">vol.i · ov3 protocol analyzer · 4.6</span>
    </div>
    <div class="mast-r">
      {#if status === 'running'}
        <span class="rec" transition:fade={{duration: 200}}>
          <span class="rec-dot"></span>REC
        </span>
        <span class="elapsed">{elapsed}</span>
        <span class="divider">│</span>
        <span class="session-badge">session #{activeId} · {lockedSpeed}</span>
      {:else if status === 'starting'}
        <span class="state-tag starting">probing…</span>
      {:else if status === 'stopping'}
        <span class="state-tag stopping">closing…</span>
      {:else if devices.length === 0}
        <span class="state-tag idle">no device</span>
      {:else}
        <span class="state-tag idle">ready</span>
      {/if}
    </div>
  </header>

  {#if error}
    <div class="toast toast-error" transition:fly={{y: -20, duration: 200}}>
      <span>{error}</span>
      <button on:click={() => (error = null)} aria-label="dismiss">✕</button>
    </div>
  {/if}

  <!-- ░░░░░░░░░░░░░░░░░░░░░░░  SIDEBAR  ░░░░░░░░░░░░░░░░░░░░░░░ -->
  <aside class="sidebar">
    <section class="console">
      <h3>CAPTURE</h3>

      <div class="field">
        <label for="dev">device</label>
        <div class="device-row">
          <select id="dev" bind:value={selectedSerial}
                  disabled={status !== 'idle' || devices.length === 0}>
            {#if devices.length === 0}
              <option value={null}>— none detected —</option>
            {:else}
              {#each devices as d (d.serial ?? `${d.bus}.${d.port_path}`)}
                <option value={d.serial}>{describeDevice(d)}</option>
              {/each}
            {/if}
          </select>
          <button class="icon-btn" on:click={rescan} disabled={status !== 'idle'}
                  title="Rescan USB bus">↻</button>
        </div>
        {#if activeDevice}
          <div class="device-meta">
            <span>{activeDevice.description}</span>
            <span class="tab-spacer">·</span>
            <span>bus {activeDevice.bus}</span>
            <span class="tab-spacer">·</span>
            <span>port {activeDevice.port_path || '?'}</span>
          </div>
        {/if}
      </div>

      <div class="field">
        <label>usb speed</label>
        <div class="speed-tabs" role="radiogroup">
          {#each SPEEDS as opt (opt)}
            <button role="radio"
                    aria-checked={speed === opt}
                    class:on={speed === opt}
                    disabled={status !== 'idle'}
                    on:click={() => (speed = opt)}>{opt}</button>
          {/each}
        </div>
        <div class="speed-hint">
          {speed === 'ls' ? '1.5 Mbps · low speed' :
           speed === 'fs' ? '12 Mbps · full speed' :
           '480 Mbps · high speed'}
        </div>
      </div>

      <div class="field">
        <label for="notes">notes</label>
        <input id="notes" type="text" bind:value={notes}
               placeholder="session label"
               disabled={status !== 'idle'} />
      </div>

      {#if status === 'idle'}
        <button class="xl start" on:click={start} disabled={!canStart}>
          <span class="glyph">▶</span> START CAPTURE
        </button>
      {:else if status === 'running'}
        <button class="xl stop" on:click={stop}>
          <span class="glyph">■</span> STOP CAPTURE
        </button>
      {:else}
        <button class="xl" disabled>
          <span class="glyph">◌</span> {status.toUpperCase()}…
        </button>
      {/if}

      {#if devices.length > 1}
        <div class="warn-inline">
          {devices.length} boards attached · libopenvizsla will open the first
          match. serial-based selection lands in 4.7.
        </div>
      {:else if devices.length === 0 && !deviceError}
        <div class="muted-inline">
          plug an ov3 into usb and click ↻ rescan
        </div>
      {/if}
      {#if deviceError}
        <div class="err-inline">{deviceError}</div>
      {/if}
    </section>

    <section class="history">
      <h3>SESSIONS</h3>
      {#if sessions.length === 0}
        <p class="muted">no history yet.</p>
      {:else}
        <ul class="sess-list">
          {#each sessions.slice(0, 12) as s (s.id)}
            <li class:live={s.status === 'live'}>
              <span class="sess-id">#{String(s.id).padStart(3, '0')}</span>
              <span class="sess-speed">{s.speed}</span>
              <span class="sess-age">{fmtSessionAge(s.started_at, s.ended_at)}</span>
              <span class="sess-status">{s.status}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </aside>

  <!-- ░░░░░░░░░░░░░░░░░░░░░░░  MAIN STAGE  ░░░░░░░░░░░░░░░░░░░░░░░ -->
  <main class="stage">

    <!-- ENDPOINTS -->
    <section class="panel panel-primary">
      <header class="panel-head">
        <h2>ENDPOINTS<span class="panel-count">
          {endpointList.length ? `/ ${String(endpointList.length).padStart(2, '0')}` : ''}
        </span></h2>
        <span class="panel-legend">live summary · 250 ms tick</span>
      </header>
      {#if activeId == null}
        <p class="empty">
          <span class="empty-rune">◇</span>
          idle — no session active
        </p>
      {:else if endpointList.length === 0}
        <p class="empty">
          <span class="empty-rune pulse">◌</span>
          waiting for first transfer on the target bus…
        </p>
      {:else}
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th class="col-key">ep</th>
                <th class="col-type">type</th>
                <th class="col-dir">dir</th>
                <th class="num">count</th>
                <th class="num">bytes</th>
                <th class="num ack-col">ack</th>
                <th class="num nak-col">nak</th>
                <th class="num err-col">err</th>
                <th class="col-run">run</th>
                <th class="col-hex">last payload</th>
              </tr>
            </thead>
            <tbody>
              {#each endpointList as e (e.key)}
                <tr>
                  <td class="col-key">{e.key}</td>
                  <td class="col-type">{e.type === 'control' ? 'control' : 'intr/blk'}</td>
                  <td class="col-dir">
                    <span class="dir-arrow">{e.direction === 'in' ? '←' : e.direction === 'out' ? '→' : '·'}</span>
                    {e.direction}
                  </td>
                  <td class="num">{fmtInt(e.count)}</td>
                  <td class="num">{fmtInt(e.bytes)}</td>
                  <td class="num ack-col">{fmtInt(e.acks)}</td>
                  <td class="num nak-col">{e.naks ? fmtInt(e.naks) : '·'}</td>
                  <td class="num err-col" class:hot={e.stalls + e.nyets + e.incompletes > 0}>
                    {e.stalls + e.nyets + e.incompletes || '·'}
                  </td>
                  <td class="col-run">
                    {e.status_run_kind || '—'}{e.status_run_kind ? `×${e.status_run_len}` : ''}
                  </td>
                  <td class="col-hex">{fmtHex(e.last_data_hex, 28)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>

    <!-- EVENTS -->
    <section class="panel">
      <header class="panel-head">
        <h2>EVENTS<span class="panel-count">
          {events.length ? `/ ${fmtInt(events.length)}` : ''}
        </span></h2>
        <span class="panel-legend">filtered stream · newest first</span>
      </header>
      {#if activeId == null}
        <p class="empty">
          <span class="empty-rune">◇</span>
          idle
        </p>
      {:else if events.length === 0}
        <p class="empty">
          <span class="empty-rune pulse">◌</span>
          no notable events yet — filter is quiet by design
        </p>
      {:else}
        <ul class="events">
          {#each events as e (e.ts_ns !== undefined
            ? `${e.ts_ns}-${e.kind}-${e.key ?? ''}`
            : `${e.kind}-${events.indexOf(e)}`)}
            <li class={e.kind} in:fly={{y: -4, duration: 140}}>
              <span class="ek-dot {e.kind}"></span>
              <span class="ek">{e.kind.replace(/_/g, ' ')}</span>
              <span class="ev-body">{formatEvent(e)}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <!-- FIREHOSE -->
    <section class="panel panel-fire">
      <details on:toggle={toggleFirehose}>
        <summary>
          <div class="fire-head">
            <h2>RAW FIREHOSE
              <span class="panel-count">
                {firehoseOpen ? `/ ${fmtInt(firehose.length)}` : ''}
              </span>
            </h2>
            <span class="fire-hint">
              {firehoseOpen ? 'subscribed — every transfer on the wire' : 'collapsed — expand to subscribe'}
            </span>
          </div>
        </summary>
        {#if firehoseOpen}
          <div class="table-wrap">
            <table class="data-table mono-small">
              <thead>
                <tr>
                  <th class="num">t (ns)</th>
                  <th>ep</th>
                  <th>dir</th>
                  <th>status</th>
                  <th class="num">len</th>
                  <th class="col-hex">data</th>
                </tr>
              </thead>
              <tbody>
                {#each firehose as t (t.ts_ns)}
                  <tr class={t.status}>
                    <td class="num">{t.ts_ns}</td>
                    <td>{t.device_addr}.{t.ep_addr}</td>
                    <td>{t.direction}</td>
                    <td class="status-{t.status}">{t.status}</td>
                    <td class="num">{t.length}</td>
                    <td class="col-hex">{fmtHex(t.data_hex, 48)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </details>
    </section>
  </main>

  <!-- ░░░░░░░░░░░░░░░░░░░░░░░  STATUS LINE  ░░░░░░░░░░░░░░░░░░░░░░░ -->
  <footer class="statusline">
    <span class="status-item">
      <span class="status-k">xfers</span>
      <span class="status-v">{fmtInt(totalXfers)}</span>
    </span>
    <span class="status-sep">·</span>
    <span class="status-item">
      <span class="status-k">ack</span>
      <span class="status-v ack">{fmtInt(totalAcks)}</span>
    </span>
    <span class="status-sep">·</span>
    <span class="status-item">
      <span class="status-k">nak</span>
      <span class="status-v nak">{fmtInt(totalNaks)}</span>
    </span>
    <span class="status-sep">·</span>
    <span class="status-item">
      <span class="status-k">err</span>
      <span class="status-v" class:hot={totalErrs > 0}>{fmtInt(totalErrs)}</span>
    </span>

    <span class="status-spacer"></span>

    <span class="status-item">
      <span class="status-k">firehose</span>
      <span class="status-v" class:on={firehoseOpen}>{firehoseOpen ? 'on' : 'off'}</span>
    </span>
    <span class="status-sep">·</span>
    <span class="status-item">
      <span class="status-k">tick</span>
      <span class="status-v">250 ms</span>
    </span>
    <span class="status-sep">·</span>
    <span class="status-item">
      <span class="status-k">ovweb</span>
      <span class="status-v">4.6.0</span>
    </span>
  </footer>
</div>

<style>
  /* ============================================================
     TOKENS — midnight + warm cream + phosphor amber
     ============================================================ */
  :global(:root) {
    /* Surfaces */
    --bg-deep:      #0a0b0f;
    --bg-panel:     #10131a;
    --bg-elev:      #171b24;
    --bg-rule:      #1e2230;

    /* Ink */
    --ink-primary:  #ebe4d1;    /* warm cream — data */
    --ink-secondary:#a79e86;    /* dulled cream — labels */
    --ink-muted:    #6a6f82;    /* cool muted — metadata */
    --ink-dim:      #2a2f3d;    /* rules, dividers */
    --ink-faint:    #1a1d27;

    /* Accent */
    --hot:          #ffb547;    /* phosphor amber */
    --hot-bright:   #ffd089;
    --hot-dim:      rgba(255, 181, 71, 0.12);
    --hot-wash:     rgba(255, 181, 71, 0.04);

    /* Signal semantics */
    --sig-ack:      #a8c975;    /* muted phosphor green (ok) */
    --sig-nak:      #6a6f82;    /* recedes */
    --sig-err:      #ff7b5c;    /* warm red (stall/overflow) */
    --sig-info:     #88b0d4;    /* cool cyan (info events) */
    --sig-ctrl:     #d1a7d8;    /* soft magenta (control xfers) */

    /* Fonts */
    --font-serif:   'Fraunces', 'Hoefler Text', 'Times New Roman', serif;
    --font-mono:    'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace;

    --tracking-hair: 0.18em;
    --tracking-body: 0.04em;
  }

  :global(*) { box-sizing: border-box; }

  :global(html), :global(body) {
    margin: 0;
    background: var(--bg-deep);
    color: var(--ink-primary);
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.45;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }

  /* Grain overlay. Very subtle — 2% opacity — for atmosphere. */
  :global(body::before) {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 999;
    opacity: 0.025;
    mix-blend-mode: screen;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
  }

  /* ============================================================
     SHELL GRID
     ============================================================ */
  .shell {
    display: grid;
    grid-template-columns: minmax(280px, 300px) 1fr;
    grid-template-rows: auto 1fr auto;
    grid-template-areas:
      "head head"
      "side main"
      "foot foot";
    min-height: 100vh;
  }

  @media (max-width: 900px) {
    .shell {
      grid-template-columns: 1fr;
      grid-template-areas: "head" "side" "main" "foot";
    }
  }

  /* ============================================================
     MASTHEAD — ovweb wordmark + session indicator
     ============================================================ */
  .masthead {
    grid-area: head;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 2rem;
    padding: 1.4rem 2rem 1.1rem;
    border-bottom: 1px solid var(--ink-dim);
    position: relative;
  }
  .masthead::after {
    /* decorative second rule, narrower, below the border */
    content: '';
    position: absolute;
    left: 2rem; bottom: -4px;
    width: 56px; height: 1px;
    background: var(--hot);
  }

  .mast-l { display: flex; align-items: baseline; gap: 1rem; }
  .brand {
    font-family: var(--font-serif);
    font-weight: 500;
    font-size: 2.6rem;
    font-variation-settings: 'SOFT' 40, 'WONK' 1, 'opsz' 144;
    letter-spacing: -0.02em;
    color: var(--ink-primary);
    line-height: 0.9;
  }
  .rule { color: var(--hot); letter-spacing: -0.1em; font-size: 1rem; }
  .dateline {
    font-size: 0.72rem;
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
    color: var(--ink-secondary);
  }

  .mast-r {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    font-size: 0.78rem;
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
  }
  .rec { color: var(--hot); font-weight: 600; display: inline-flex; align-items: center; gap: 0.4rem; }
  .rec-dot {
    width: 9px; height: 9px;
    background: var(--hot);
    display: inline-block;
    animation: pulse-dot 1.6s ease-in-out infinite;
    box-shadow: 0 0 8px var(--hot-dim);
  }
  @keyframes pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.45; transform: scale(0.85); }
  }
  .elapsed {
    font-variant-numeric: tabular-nums;
    color: var(--ink-primary);
    letter-spacing: 0.08em;
    font-size: 0.9rem;
    font-weight: 500;
  }
  .divider { color: var(--ink-dim); font-weight: 300; }
  .session-badge { color: var(--ink-secondary); }
  .state-tag {
    color: var(--ink-secondary);
    padding: 0.2rem 0.55rem;
    border: 1px solid var(--ink-dim);
    font-weight: 500;
  }
  .state-tag.starting { color: var(--hot); border-color: var(--hot); }
  .state-tag.stopping { color: var(--sig-err); border-color: var(--sig-err); }
  .state-tag.idle     { color: var(--ink-muted); }

  /* ============================================================
     TOAST
     ============================================================ */
  .toast {
    position: fixed;
    top: 1rem; right: 1rem;
    z-index: 50;
    background: var(--bg-elev);
    border: 1px solid var(--sig-err);
    border-left-width: 3px;
    padding: 0.6rem 0.8rem;
    display: flex; gap: 0.8rem; align-items: center;
    font-size: 0.82rem;
    max-width: 480px;
  }
  .toast-error { color: #ffccc0; }
  .toast button {
    background: transparent; border: 0; color: inherit; cursor: pointer;
    font-family: var(--font-mono); font-size: 0.9rem; opacity: 0.7;
  }
  .toast button:hover { opacity: 1; }

  /* ============================================================
     SIDEBAR
     ============================================================ */
  .sidebar {
    grid-area: side;
    border-right: 1px solid var(--ink-dim);
    padding: 1.5rem 1.25rem 1.5rem 2rem;
    display: flex;
    flex-direction: column;
    gap: 2rem;
    background:
      linear-gradient(180deg, var(--hot-wash) 0%, transparent 40%),
      var(--bg-deep);
  }

  .sidebar h3 {
    font-family: var(--font-serif);
    font-weight: 500;
    font-variation-settings: 'SOFT' 20, 'opsz' 24;
    font-size: 0.72rem;
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
    color: var(--hot);
    margin: 0 0 0.9rem;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--ink-dim);
    display: flex; align-items: center;
  }
  .sidebar h3::after {
    content: '';
    flex: 1; margin-left: 0.8rem;
    height: 1px;
    background: repeating-linear-gradient(to right,
      var(--ink-dim) 0 3px, transparent 3px 6px);
  }

  .console { display: flex; flex-direction: column; gap: 1rem; }

  .field { display: flex; flex-direction: column; gap: 0.4rem; }
  .field > label {
    font-size: 0.68rem;
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
    color: var(--ink-muted);
    font-weight: 500;
  }

  .device-row { display: flex; gap: 0.4rem; }

  select, input[type="text"] {
    background: var(--bg-panel);
    color: var(--ink-primary);
    border: 1px solid var(--ink-dim);
    padding: 0.5rem 0.6rem;
    font: inherit;
    font-size: 0.82rem;
    border-radius: 0;
    width: 100%;
    transition: border-color 120ms ease;
  }
  select:focus, input:focus {
    outline: none;
    border-color: var(--hot);
  }
  select:disabled, input:disabled { opacity: 0.5; }

  .icon-btn {
    background: var(--bg-panel);
    border: 1px solid var(--ink-dim);
    color: var(--ink-primary);
    width: 2.4rem;
    flex-shrink: 0;
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: 0.95rem;
    border-radius: 0;
    transition: all 120ms ease;
  }
  .icon-btn:hover:not(:disabled) { color: var(--hot); border-color: var(--hot); }
  .icon-btn:disabled { opacity: 0.4; cursor: default; }

  .device-meta {
    font-size: 0.7rem;
    color: var(--ink-muted);
    letter-spacing: 0.02em;
    padding-top: 0.2rem;
  }
  .tab-spacer { color: var(--ink-dim); padding: 0 0.35rem; }

  .speed-tabs {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border: 1px solid var(--ink-dim);
  }
  .speed-tabs button {
    background: transparent;
    border: none;
    border-right: 1px solid var(--ink-dim);
    padding: 0.55rem 0;
    color: var(--ink-secondary);
    font: 500 0.78rem var(--font-mono);
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
    cursor: pointer;
    transition: all 140ms ease;
  }
  .speed-tabs button:last-child { border-right: none; }
  .speed-tabs button:hover:not(:disabled):not(.on) {
    color: var(--ink-primary);
    background: var(--bg-panel);
  }
  .speed-tabs button.on {
    color: var(--bg-deep);
    background: var(--hot);
    font-weight: 600;
  }
  .speed-tabs button:disabled { opacity: 0.4; cursor: default; }
  .speed-hint {
    font-size: 0.7rem;
    color: var(--ink-muted);
    padding-top: 0.25rem;
    letter-spacing: 0.02em;
  }

  button.xl {
    padding: 0.95rem 0.6rem;
    background: var(--hot);
    color: var(--bg-deep);
    border: 1px solid var(--hot);
    font: 600 0.82rem var(--font-mono);
    letter-spacing: 0.3em;
    text-transform: uppercase;
    cursor: pointer;
    text-align: left;
    display: flex;
    align-items: center;
    gap: 0.9rem;
    transition: all 120ms ease;
    border-radius: 0;
    margin-top: 0.5rem;
  }
  button.xl .glyph { font-size: 0.85rem; letter-spacing: 0; }
  button.xl:hover:not(:disabled) {
    background: var(--hot-bright);
    border-color: var(--hot-bright);
    box-shadow: 0 0 20px var(--hot-dim);
  }
  button.xl.stop {
    background: transparent;
    color: var(--sig-err);
    border-color: var(--sig-err);
  }
  button.xl.stop:hover:not(:disabled) {
    background: var(--sig-err);
    color: var(--bg-deep);
    box-shadow: 0 0 20px rgba(255, 123, 92, 0.2);
  }
  button.xl:disabled {
    background: transparent;
    color: var(--ink-dim);
    border-color: var(--ink-dim);
    cursor: default;
  }

  .warn-inline, .muted-inline, .err-inline {
    font-size: 0.72rem;
    padding: 0.45rem 0.55rem;
    line-height: 1.45;
  }
  .warn-inline  { color: var(--hot); border-left: 2px solid var(--hot); background: var(--hot-wash); }
  .muted-inline { color: var(--ink-muted); border-left: 2px solid var(--ink-dim); }
  .err-inline   { color: var(--sig-err); border-left: 2px solid var(--sig-err); background: rgba(255,123,92,0.05); }

  /* Sessions history */
  .history .sess-list { list-style: none; margin: 0; padding: 0; }
  .history .sess-list li {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    gap: 0.7rem;
    padding: 0.45rem 0;
    border-bottom: 1px dashed var(--ink-dim);
    font-size: 0.78rem;
    color: var(--ink-secondary);
    align-items: baseline;
  }
  .sess-id     { color: var(--ink-primary); font-weight: 500; font-variant-numeric: tabular-nums; }
  .sess-speed  { color: var(--ink-muted); text-transform: uppercase; letter-spacing: var(--tracking-hair); font-size: 0.68rem; }
  .sess-age    { color: var(--ink-muted); font-variant-numeric: tabular-nums; }
  .sess-status { color: var(--ink-muted); text-transform: uppercase; letter-spacing: var(--tracking-hair); font-size: 0.68rem; }
  .sess-list li.live .sess-id     { color: var(--hot); }
  .sess-list li.live .sess-status { color: var(--hot); }

  /* ============================================================
     MAIN STAGE
     ============================================================ */
  .stage {
    grid-area: main;
    padding: 1.5rem 2rem 2rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    overflow-y: auto;
  }

  /* ============================================================
     PANEL — corner brackets on top-left & bottom-right
     ============================================================ */
  .panel {
    position: relative;
    border: 1px solid var(--ink-dim);
    background: var(--bg-panel);
    padding: 1rem 1.2rem 1.1rem;
  }
  .panel::before,
  .panel::after {
    content: '';
    position: absolute;
    width: 16px; height: 16px;
    pointer-events: none;
  }
  .panel::before {
    top: -1px; left: -1px;
    border-top: 2px solid var(--hot);
    border-left: 2px solid var(--hot);
  }
  .panel::after {
    bottom: -1px; right: -1px;
    border-bottom: 2px solid var(--hot);
    border-right: 2px solid var(--hot);
  }
  .panel-primary::before,
  .panel-primary::after {
    width: 22px; height: 22px;
    border-width: 2px;
  }

  .panel-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.85rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid var(--ink-dim);
  }
  .panel-head h2 {
    font-family: var(--font-serif);
    font-weight: 500;
    font-variation-settings: 'SOFT' 30, 'WONK' 1, 'opsz' 36;
    font-size: 1.05rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 0;
    color: var(--ink-primary);
  }
  .panel-count {
    color: var(--hot);
    font-family: var(--font-mono);
    font-size: 0.78rem;
    margin-left: 0.5rem;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
    letter-spacing: 0;
  }
  .panel-legend {
    font-size: 0.7rem;
    color: var(--ink-muted);
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
  }

  .empty {
    color: var(--ink-muted);
    font-size: 0.85rem;
    padding: 1.5rem 0 1rem;
    display: flex; align-items: center; gap: 0.8rem;
  }
  .empty-rune {
    font-size: 1.1rem;
    color: var(--ink-dim);
  }
  .empty-rune.pulse { color: var(--hot); animation: breathe 2.4s ease-in-out infinite; }
  @keyframes breathe {
    0%, 100% { opacity: 0.35; }
    50%      { opacity: 1;    }
  }

  /* ============================================================
     DATA TABLES
     ============================================================ */
  .table-wrap { overflow-x: auto; }
  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
    font-family: var(--font-mono);
  }
  .data-table th, .data-table td {
    padding: 0.4rem 0.8rem 0.4rem 0;
    text-align: left;
    vertical-align: baseline;
  }
  .data-table th {
    color: var(--ink-muted);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: var(--tracking-hair);
    font-size: 0.68rem;
    border-bottom: 1px solid var(--ink-dim);
    position: sticky; top: 0;
    background: var(--bg-panel);
  }
  .data-table tbody tr {
    border-bottom: 1px dotted var(--ink-faint);
  }
  .data-table tbody tr:hover {
    background: var(--hot-wash);
  }

  .data-table .num {
    font-variant-numeric: tabular-nums;
    text-align: right;
    color: var(--ink-primary);
  }
  .data-table .ack-col { color: var(--sig-ack); }
  .data-table .nak-col { color: var(--sig-nak); }
  .data-table .err-col { color: var(--ink-muted); }
  .data-table .err-col.hot { color: var(--sig-err); font-weight: 600; }
  .data-table .col-key { color: var(--hot); font-weight: 500; }
  .data-table .col-type { color: var(--ink-secondary); }
  .data-table .col-dir  { color: var(--ink-secondary); text-transform: lowercase; }
  .dir-arrow { color: var(--hot); margin-right: 0.35rem; font-weight: 600; }
  .data-table .col-run  { color: var(--ink-muted); font-size: 0.72rem; }
  .data-table .col-hex  { color: var(--sig-info); font-size: 0.76rem; letter-spacing: 0.02em; }

  .data-table.mono-small { font-size: 0.74rem; }
  .data-table.mono-small .col-hex { font-size: 0.72rem; }

  /* Firehose status rows — retain the Phase 4.5 semantics. */
  tr .status-ack        { color: var(--sig-ack); }
  tr .status-nak        { color: var(--sig-nak); }
  tr .status-stall      { color: var(--sig-err); }
  tr .status-nyet       { color: var(--sig-err); }
  tr .status-incomplete { color: var(--hot); }

  /* ============================================================
     EVENTS FEED
     ============================================================ */
  .events {
    list-style: none;
    margin: 0;
    padding: 0;
    max-height: 28rem;
    overflow-y: auto;
  }
  .events li {
    display: grid;
    grid-template-columns: 10px minmax(9rem, 11rem) 1fr;
    gap: 0.7rem;
    padding: 0.4rem 0;
    border-bottom: 1px dotted var(--ink-faint);
    align-items: baseline;
    font-size: 0.82rem;
  }
  .ek-dot {
    width: 8px; height: 8px;
    display: inline-block;
    margin-top: 0.35rem;
    background: var(--ink-muted);
  }
  .ek-dot.new_endpoint    { background: var(--sig-info); }
  .ek-dot.control_transfer{ background: var(--sig-ctrl); }
  .ek-dot.payload_change  { background: var(--sig-ack); }
  .ek-dot.status_flip     { background: var(--hot); }
  .ek-dot.speed_locked    { background: var(--sig-ack); }
  .ek-dot.speed_lost      { background: var(--sig-err); }
  .ek-dot.overflow        { background: var(--sig-err); }

  .ek {
    color: var(--ink-muted);
    text-transform: uppercase;
    letter-spacing: var(--tracking-hair);
    font-size: 0.68rem;
    font-weight: 500;
  }
  .ev-body {
    color: var(--ink-primary);
  }
  .events li.overflow .ev-body,
  .events li.speed_lost .ev-body { color: var(--sig-err); }
  .events li.speed_locked .ev-body { color: var(--sig-ack); font-weight: 500; }
  .events li.control_transfer .ev-body { color: var(--sig-ctrl); }
  .events li.payload_change .ev-body { color: var(--ink-primary); }
  .events li.payload_change .ev-body { font-family: var(--font-mono); }

  /* ============================================================
     FIREHOSE <details>
     ============================================================ */
  .panel-fire { padding: 0; }
  .panel-fire details { display: block; }
  .panel-fire summary {
    cursor: pointer;
    list-style: none;
    padding: 1rem 1.2rem;
  }
  .panel-fire summary::-webkit-details-marker { display: none; }
  .fire-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }
  .fire-head h2 {
    font-family: var(--font-serif);
    font-variation-settings: 'SOFT' 30, 'opsz' 36;
    font-size: 1.05rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 0;
    color: var(--ink-secondary);
  }
  .panel-fire details[open] summary { border-bottom: 1px solid var(--ink-dim); }
  .panel-fire details[open] .fire-head h2 { color: var(--ink-primary); }
  .panel-fire .fire-hint {
    font-size: 0.7rem;
    color: var(--ink-muted);
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
  }
  .panel-fire .table-wrap {
    max-height: 22rem;
    padding: 0.5rem 1.2rem 1rem;
  }

  /* ============================================================
     STATUS LINE
     ============================================================ */
  .statusline {
    grid-area: foot;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 2rem;
    border-top: 1px solid var(--ink-dim);
    background: var(--bg-panel);
    font-size: 0.72rem;
    letter-spacing: var(--tracking-hair);
    text-transform: uppercase;
    color: var(--ink-muted);
  }
  .status-item { display: inline-flex; align-items: baseline; gap: 0.4rem; }
  .status-k    { color: var(--ink-muted); font-weight: 400; }
  .status-v    {
    color: var(--ink-primary);
    font-variant-numeric: tabular-nums;
    font-weight: 500;
    letter-spacing: 0.02em;
  }
  .status-v.ack  { color: var(--sig-ack); }
  .status-v.nak  { color: var(--sig-nak); }
  .status-v.hot  { color: var(--sig-err); font-weight: 600; }
  .status-v.on   { color: var(--hot); }
  .status-sep    { color: var(--ink-dim); }
  .status-spacer { flex: 1; }

  /* Custom scrollbars — thin, warm, mostly invisible. */
  :global(::-webkit-scrollbar)        { width: 8px; height: 8px; }
  :global(::-webkit-scrollbar-track)  { background: transparent; }
  :global(::-webkit-scrollbar-thumb)  { background: var(--ink-dim); }
  :global(::-webkit-scrollbar-thumb:hover) { background: var(--ink-muted); }
</style>
