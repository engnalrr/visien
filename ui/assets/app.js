/* Visien UI. Talks to the local engine server (127.0.0.1) and, in the app window, to the native bridge. */
(() => {
  'use strict';

  // ---------------------------------------------------------------- helpers

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const icon = (name) => `<svg class="i"><use href="#i-${name}"/></svg>`;
  const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const store = {
    get(key, fallback) {
      try { const raw = localStorage.getItem('visien.' + key); return raw === null ? fallback : JSON.parse(raw); } catch { return fallback; }
    },
    set(key, value) { try { localStorage.setItem('visien.' + key, JSON.stringify(value)); } catch { /* storage unavailable */ } },
  };

  async function api(path, body, method) {
    const options = { method: method || (body !== undefined ? 'POST' : 'GET'), headers: {} };
    if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    const response = await fetch('/api' + path, options);
    let data = null;
    try { data = await response.json(); } catch { /* empty */ }
    if (!response.ok) {
      const error = new Error((data && data.detail) || response.statusText || 'Request failed');
      error.data = data; error.status = response.status;
      throw error;
    }
    return data;
  }

  function stable(value) {
    if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map((k) => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
    if (typeof value === 'number') return String(Math.round(value * 1e6) / 1e6);
    return JSON.stringify(value);
  }
  const clone = (value) => JSON.parse(JSON.stringify(value));

  function fmtTime(seconds, withHours = false) {
    seconds = Math.max(0, seconds || 0);
    const hh = Math.floor(seconds / 3600), mm = Math.floor((seconds % 3600) / 60), ss = seconds % 60;
    const core = `${String(mm).padStart(2, '0')}:${ss.toFixed(2).padStart(5, '0')}`;
    return withHours || hh ? `${String(hh).padStart(2, '0')}:${core}` : core;
  }
  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined || !isFinite(seconds)) return '';
    seconds = Math.round(seconds);
    if (seconds < 60) return `${seconds} s`;
    const m = Math.floor(seconds / 60), s = seconds % 60;
    if (m < 60) return `${m}:${String(s).padStart(2, '0')}`;
    return `${Math.floor(m / 60)} h ${m % 60} min`;
  }
  const fmtFps = (fps) => (fps ? `${(Math.round(fps * 1000) / 1000).toString()} fps` : '');
  const fmtSize = (w, h) => (w && h ? `${w}×${h}` : '');
  function fmtBytes(n) {
    if (!n) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
  }

  // ---------------------------------------------------------------- native bridge

  const bridgeReady = new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) { resolve(true); return; }
    window.addEventListener('pywebviewready', () => resolve(true), { once: true });
    setTimeout(() => resolve(Boolean(window.pywebview && window.pywebview.api)), 2500);
  });
  async function native(name, ...args) {
    await bridgeReady;
    const fn = window.pywebview && window.pywebview.api && window.pywebview.api[name];
    return fn ? fn(...args) : undefined;
  }
  async function hasNative() { await bridgeReady; return Boolean(window.pywebview && window.pywebview.api); }

  // ---------------------------------------------------------------- state

  const S = {
    schema: null, stage: {}, kind: store.get('kind', 'video'),
    settings: null, baseline: null, presetId: store.get('presetId', null), presetName: store.get('presetName', 'Custom'),
    presets: [], media: [], activeId: store.get('activeId', null), picked: new Set(store.get('picked', [])),
    engine: null, config: {}, devices: [], releaseUrl: '',
    collapsed: store.get('collapsed', {}), advanced: {}, colorTab: 'adjust',
    view: { mode: store.get('viewMode', 'split'), split: 0.5, zoom: null, cx: 0.5, cy: 0.5, lossless: false },
    time: 0, previewLength: Number(store.get('previewLength', 3)),
    previewJob: null, preview: null, previewOn: false, previewHash: '', playing: false,
    queue: { jobs: [], running: false, log: [] }, queueOpen: store.get('queueOpen', false), showLog: false,
    plan: null, checks: { problems: [], warnings: [] },
    mode: store.get('mode', 'easy'), models: null,
  };

  const activeMedia = () => S.media.find((m) => m.id === S.activeId) || null;
  const keyOf = (f) => (S.kind === 'image' && f.image_key ? f.image_key : f.key);
  const defOf = (f) => (S.kind === 'image' && f.image_key ? f.image_default : f.default);
  const optsOf = (f) => (S.kind === 'image' && f.image_options ? f.image_options : f.options) || [];
  const enabledKey = () => `${S.kind}_enabled_stages`;
  const aiKey = () => `vz_${S.kind}_ai`;
  const orderKey = () => `vz_${S.kind}_order`;
  const veOrderKey = () => `${S.kind}_stage_order`;
  const isAI = (id) => ((S.schema && S.schema.ai_ids) || []).includes(id);
  const onSet = () => new Set([...(S.settings[enabledKey()] || []), ...(S.settings[aiKey()] || [])]);
  const uiTip = (key) => (S.schema && S.schema.ui_tips && S.schema.ui_tips[key]) || '';
  const settingsHash = (kind = S.kind) => stable(relevantSettings(kind));

  function relevantSettings(kind) {
    const out = {};
    const take = (f) => {
      if (!f.key || f.key.startsWith('_') || !f.kinds.includes(kind)) return;
      const key = kind === 'image' && f.image_key ? f.image_key : f.key;
      out[key] = S.settings[key];
    };
    S.schema.stages.forEach((st) => st.fields.forEach(take));
    S.schema.export.forEach(take);
    out[`${kind}_enabled_stages`] = [...S.settings[`${kind}_enabled_stages`]].sort();
    out[`vz_${kind}_ai`] = [...(S.settings[`vz_${kind}_ai`] || [])].sort();
    out[`vz_${kind}_order`] = S.settings[`vz_${kind}_order`];
    out.vz_output_short = S.settings.vz_output_short || 0;
    return out;
  }

  function saveLocal() {
    store.set('settings', S.settings);
    store.set('baseline', S.baseline);
    store.set('presetId', S.presetId);
    store.set('presetName', S.presetName);
    store.set('kind', S.kind);
    store.set('collapsed', S.collapsed);
  }

  // ---------------------------------------------------------------- toasts & modals

  function toast(text, kind = 'info', ms = 5200) {
    const node = h('div', { class: `toast ${kind}`, html: icon(kind === 'err' ? 'alert' : kind === 'ok' ? 'check' : 'log') + `<span>${esc(text)}</span>` });
    $('#toasts').append(node);
    setTimeout(() => node.remove(), kind === 'err' ? Math.max(ms, 9000) : ms);
    node.addEventListener('click', () => node.remove());
  }
  const fail = (error) => toast(error && error.message ? error.message : String(error), 'err');

  function modal({ title, body, actions = [], size = '' }) {
    const backdrop = h('div', { class: 'modal-backdrop' });
    const close = () => { backdrop.remove(); document.removeEventListener('keydown', onKey, true); };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const foot = h('div', { class: 'modal-foot' }, actions.map((a) => h('button', {
      class: `btn ${a.primary ? 'btn-primary' : a.danger ? 'btn-quiet btn-danger' : 'btn-quiet'}`,
      onclick: async () => { if (a.run) { const keep = await a.run(close); if (keep === true) return; } close(); },
    }, a.label)));
    const box = h('div', { class: `modal ${size}`, role: 'dialog', 'aria-modal': 'true' },
      h('div', { class: 'modal-head' }, h('h3', {}, title), h('button', { class: 'icon-btn', title: 'Close', html: icon('x'), onclick: close })),
      h('div', { class: 'modal-body' }, body), actions.length ? foot : null);
    backdrop.append(box);
    backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });
    document.addEventListener('keydown', onKey, true);
    $('#modalRoot').append(backdrop);
    const first = box.querySelector('input, select, textarea');
    if (first) setTimeout(() => first.focus(), 30);
    return { close, box };
  }

  function confirmModal(title, text, label = 'Continue', danger = false) {
    return new Promise((resolve) => {
      let answered = false;
      const m = modal({
        title, size: 'small', body: h('p', {}, text),
        actions: [{ label: 'Cancel', run: () => { answered = true; resolve(false); } },
          { label, primary: !danger, danger, run: () => { answered = true; resolve(true); } }],
      });
      const observer = new MutationObserver(() => { if (!m.box.isConnected) { observer.disconnect(); if (!answered) resolve(false); } });
      observer.observe($('#modalRoot'), { childList: true });
    });
  }

  function promptModal(title, label, value = '', extra = null) {
    return new Promise((resolve) => {
      let answered = false;
      const input = h('input', { class: 'input', value, spellcheck: 'false' });
      const body = h('div', { style: 'display:flex;flex-direction:column;gap:14px' }, h('label', { class: 'lbl' }, label, input), extra);
      const m = modal({
        title, size: 'small', body,
        actions: [{ label: 'Cancel', run: () => { answered = true; resolve(null); } },
          { label: 'OK', primary: true, run: () => { answered = true; resolve(input.value.trim()); } }],
      });
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { answered = true; resolve(input.value.trim()); m.close(); } });
      const observer = new MutationObserver(() => { if (!m.box.isConnected) { observer.disconnect(); if (!answered) resolve(null); } });
      observer.observe($('#modalRoot'), { childList: true });
    });
  }

  // ---------------------------------------------------------------- file picking

  async function pickMedia() {
    if (await hasNative()) return (await native('pick_media')) || [];
    const text = await promptModal('Add media', 'Paste full file or folder paths, one per line (browser mode cannot open the Windows file dialog).');
    return text ? text.split(/\r?\n/).map((p) => p.trim().replace(/^"|"$/g, '')).filter(Boolean) : [];
  }
  async function pickFolder(start = '') {
    if (await hasNative()) return (await native('pick_folder', start)) || '';
    return (await promptModal('Choose folder', 'Folder path', start)) || '';
  }
  async function pickFile(filter) {
    if (await hasNative()) return (await native('pick_file', filter || 'All files (*.*)')) || '';
    return (await promptModal('Choose file', 'File path')) || '';
  }

  async function addPaths(paths) {
    if (!paths || !paths.length) return;
    try {
      const result = await api('/media', { paths });
      S.media = result.items;
      result.added.forEach((id) => S.picked.add(id));
      if (result.added.length && (!S.activeId || !activeMedia())) activate(result.added[0]);
      else if (result.added.length === 1) activate(result.added[0]);
      renderMedia();
      if (result.skipped.length) {
        toast(`Skipped ${result.skipped.length} file(s):\n` + result.skipped.slice(0, 4).map((s) => `${s.path.split(/[\\/]/).pop()}: ${s.error}`).join('\n'), 'err');
      }
      if (result.added.length) toast(`Added ${result.added.length} file${result.added.length > 1 ? 's' : ''}.`, 'ok', 2500);
    } catch (error) { fail(error); }
  }

  // ---------------------------------------------------------------- presets

  function applyPreset(preset) {
    S.settings = Object.assign(clone(S.schema.defaults), clone(preset.settings));
    S.baseline = clone(S.settings);
    S.presetId = preset.id;
    S.presetName = preset.name;
    S.collapsed = {};
    saveLocal();
    renderAll();
  }

  const isModified = () => S.baseline && stable(S.settings) !== stable(S.baseline);

  function renderPresetButton() {
    $('#presetName').textContent = S.presetName || 'Custom';
    $('#presetModified').hidden = !isModified();
  }

  async function loadPresets() {
    try { S.presets = await api('/presets'); } catch (error) { fail(error); }
  }

  function openPresetMenu() {
    const menu = $('#presetMenu');
    if (!menu.hidden) { menu.hidden = true; return; }
    menu.innerHTML = '';
    const current = S.presets.find((p) => p.id === S.presetId);
    const modified = isModified();
    const item = (title, desc, iconName, run, extraClass = '', disabled = false) => h('button', {
      class: `menu-item ${extraClass}`, disabled, onclick: () => { menu.hidden = true; run(); },
    }, h('span', { html: icon(iconName) }), h('span', { class: 'mi-main' }, h('span', { class: 'mi-title' }, title), desc ? h('span', { class: 'mi-desc' }, desc) : null));
    const choose = (preset) => async () => {
      if (isModified() && !(await confirmModal('Load preset', `Your changes to “${S.presetName}” will be replaced by “${preset.name}”.`, 'Load preset'))) return;
      applyPreset(preset);
      toast(`Loaded “${preset.name}”.`, 'ok', 2200);
    };
    const builtin = S.presets.filter((p) => p.builtin);
    const mine = S.presets.filter((p) => !p.builtin);
    let section = '';
    builtin.forEach((p) => {
      const group = p.group || 'Visien presets';
      if (group !== section) { section = group; menu.append(h('div', { class: 'menu-section' }, group)); }
      const node = item(p.name, p.description, 'preset', choose(p), p.id === S.presetId ? 'current' : '');
      if (p.ai && p.ai.length) node.querySelector('.mi-title').append(h('span', { class: 'badge-ai', 'data-tip': `Uses ${p.ai.join(', ')}: needs the AI models (Settings › AI models).` }, 'AI'));
      menu.append(node);
    });
    menu.append(h('div', { class: 'menu-section' }, 'Your presets'));
    if (!mine.length) menu.append(h('div', { class: 'menu-item', disabled: true }, h('span', { class: 'mi-desc' }, 'Presets you save appear here.')));
    mine.forEach((p) => menu.append(item(p.name, p.description, 'preset', choose(p), p.id === S.presetId ? 'current' : '')));
    menu.append(h('div', { class: 'menu-sep' }));
    menu.append(item('Save as new preset…', '', 'plus', savePresetAs));
    if (current && !current.builtin) menu.append(item(`Save changes to “${current.name}”`, '', 'check', () => savePreset(current.name, current.description), '', !modified));
    if (current) menu.append(item(`Revert to “${current.name}”`, '', 'reset', () => applyPreset(current), '', !modified));
    menu.append(item('Copy settings from Visual Enhancer', 'Reads the settings Visual Enhancer saved last (close it first so they are saved).', 'reveal', copyFromVE));
    menu.append(item('Import preset file…', 'A .json exported from Visual Enhancer or Visien.', 'folder', importPreset));
    menu.append(item('Export current settings…', 'Saves a .json that Visual Enhancer can import too.', 'reveal', exportPreset));
    if (current && !current.builtin) menu.append(item(`Delete “${current.name}”`, '', 'trash', () => deletePreset(current), 'danger'));
    menu.hidden = false;
  }

  async function savePreset(name, description = '') {
    try {
      const saved = await api('/presets', { name, description, settings: S.settings });
      await loadPresets();
      S.presetId = saved.id; S.presetName = saved.name; S.baseline = clone(S.settings);
      saveLocal(); renderPresetButton();
      toast(`Saved “${saved.name}”.`, 'ok', 2500);
    } catch (error) { fail(error); }
  }
  async function savePresetAs() {
    const desc = h('input', { class: 'input', placeholder: 'What is it for? (optional)' });
    const name = await promptModal('Save preset', 'Name', S.presetName && !S.presets.find((p) => p.id === S.presetId && p.builtin) ? S.presetName : '', h('label', { class: 'lbl' }, 'Description', desc));
    if (name) await savePreset(name, desc.value.trim());
  }
  async function deletePreset(preset) {
    if (!(await confirmModal('Delete preset', `Delete “${preset.name}”? This removes its file.`, 'Delete', true))) return;
    try {
      S.presets = await api('/presets/' + encodeURIComponent(preset.id), undefined, 'DELETE');
      S.presetId = null; S.presetName = 'Custom'; S.baseline = null; saveLocal(); renderPresetButton();
    } catch (error) { fail(error); }
  }
  async function importPreset() {
    const path = await (await hasNative() ? native('pick_preset') : promptModal('Import preset', 'Path to the .json preset'));
    if (!path) return;
    try { const saved = await api('/presets/import', { path }); await loadPresets(); applyPreset(saved); toast(`Imported “${saved.name}”.`, 'ok'); } catch (error) { fail(error); }
  }
  async function exportPreset() {
    const path = await (await hasNative() ? native('save_preset', S.presetName || 'Visien') : promptModal('Export settings', 'Save as (full path to a .json file)'));
    if (!path) return;
    try { const result = await api('/presets/export', { path, settings: S.settings, name: S.presetName || 'Visien' }); toast(`Exported to ${result.path}`, 'ok'); } catch (error) { fail(error); }
  }
  async function copyFromVE() {
    const name = await promptModal('Copy settings from Visual Enhancer', 'Save them as a preset named', 'From Visual Enhancer',
      h('p', { class: 'field-hint' }, 'Visual Enhancer saves its settings when you change them and when it closes. The control mask is not copied.'));
    if (!name) return;
    try { const saved = await api('/presets/from-ve', { name }); await loadPresets(); applyPreset(saved); toast(`Copied Visual Enhancer's settings into “${saved.name}”.`, 'ok'); } catch (error) { fail(error); }
  }

  // ---------------------------------------------------------------- pipeline cards

  function findField(stage, baseKey) {
    const fields = stage ? stage.fields : S.schema.export;
    return fields.find((f) => f.key === baseKey) || S.schema.export.find((f) => f.key === baseKey);
  }
  function condOK(stage, cond) {
    if (!cond) return true;
    return Object.entries(cond).every(([k, v]) => {
      const f = findField(stage, k);
      const actual = S.settings[f ? keyOf(f) : k];
      return Array.isArray(v) ? v.includes(actual) : actual === v;
    });
  }
  const sameValue = (a, b) => (typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-9 : a === b);

  function fieldVisible(stage, f) {
    if (!f.kinds.includes(S.kind)) return false;
    if (f.tab && f.tab !== S.colorTab) return false;
    if (f.advanced && !S.advanced[stage ? stage.id : 'export']) return false;
    if (stage === null && f.hide_for_codec && f.hide_for_codec.includes(S.settings.codec)) return false;
    return condOK(stage, f.show_if);
  }

  function optionLabel(f, value) {
    const opt = optsOf(f).find((o) => sameValue(o.value, value));
    return opt ? opt.label : `Unavailable: ${value}`;
  }

  function summaryOf(stage) {
    const short = Number(S.settings.vz_output_short) || 0;
    if (stage.id === 'super_resolution' && short > 0) {
      const q = stage.fields.find((f) => f.key === 'upscale_vsr_quality');
      return `${optionLabel(q, S.settings[keyOf(q)])} · ${short === 2160 ? '4K' : short + 'p'} by short side`;
    }
    const parts = [];
    for (const f of stage.fields) {
      if (parts.length >= 3) break;
      if (!f.key || f.type === 'heading' || f.type === 'tabs' || f.advanced || !fieldVisible(stage, f)) continue;
      const v = S.settings[keyOf(f)];
      if (f.type === 'slider') parts.push(`${Number(v).toFixed(f.precision ?? 2)}${f.unit && f.unit !== '%' ? '' : f.unit || ''}`);
      else if (f.type === 'select' || f.type === 'segment') parts.push(optionLabel(f, v).replace(/ · .*$/, ''));
      else if (f.type === 'toggle') { if (v) parts.push(f.label); }
      else if (f.type === 'path') parts.push(v ? String(v).split(/[\\/]/).pop() : 'no file');
      else if (f.type === 'vsr_mode') parts.push(vsrLabel(v));
      else if (f.type === 'fps') parts.push(`${v} fps`);
      else if (f.type === 'text') parts.push(String(v));
      else if (f.type === 'number') parts.push(String(v));
    }
    return parts.join(' · ');
  }

  function vsrFamilies(f) { return f.families; }
  function vsrLabel(mode) {
    const f = S.schema.stages.find((s) => s.id === 'vfx_vsr').fields[0];
    for (const fam of f.families) for (const [value, label] of fam.levels) if (value === mode) return `${fam.label.replace(' Upscaling', '')} ${label}`;
    return String(mode);
  }

  function setValue(key, value, { rerender = true } = {}) {
    S.settings[key] = value;
    // editing the RTX Super Resolution size by hand replaces Easy mode's "size by short side"
    if (/^upscale_(image_)?(size_mode|scale_factor|width|height|aspect_lock)$/.test(key)) S.settings.vz_output_short = 0;
    if (key === 'codec') {
      const allowed = S.schema.containers[value] || ['MP4'];
      if (!allowed.includes(S.settings.container)) S.settings.container = allowed[0];
      if (value.startsWith('H.264')) S.settings.hdr_mode = false;
    }
    if (key === 'image_format' && !['PNG', 'TIFF'].includes(value) && S.settings.image_bit_depth === 16) S.settings.image_bit_depth = 8;
    if (rerender) renderCards({ keepScroll: true });
    changed();
  }

  function lockedHeight(f) {
    // With "Lock Aspect Ratio" on, Visual Enhancer derives the height from the width and the input.
    const lockKey = { upscale_height: 'upscale_aspect_lock', upscale_image_height: 'upscale_image_aspect_lock', vfx_height: 'vfx_aspect_lock' }[keyOf(f)];
    const m = activeMedia();
    if (!lockKey || !S.settings[lockKey] || !m || !m.width) return null;
    const widthKey = keyOf(f).replace('height', 'width');
    let height = Math.round(S.settings[widthKey] * m.height / m.width);
    if (S.kind === 'video') height += height % 2;
    return height;
  }

  let changeTimer = null;
  function changed() {
    saveLocal();
    renderPresetButton();
    updateRenderButton();
    renderViewerStatus();
    clearTimeout(changeTimer);
    changeTimer = setTimeout(refreshPlan, 320);
  }

  // Turns a stage on or off without redrawing. Visual Enhancer stages live in <kind>_enabled_stages, Visien's AI
  // stages in vz_<kind>_ai; exclusive groups (frame generation) span both lists.
  function applyEnabled(stageId, on, quiet = false) {
    let list = S.settings[enabledKey()].filter((x) => x !== stageId);
    let ai = (S.settings[aiKey()] || []).filter((x) => x !== stageId);
    if (on) {
      const stage = S.stage[stageId];
      const off = [];
      const drop = (x) => {
        if (list.includes(x)) { list = list.filter((y) => y !== x); off.push(x); }
        if (ai.includes(x)) { ai = ai.filter((y) => y !== x); off.push(x); }
      };
      (stage.excludes || []).forEach(drop);
      if (stage.group) S.schema.stages.filter((o) => o.group === stage.group && o.id !== stageId).forEach((o) => drop(o.id));
      if (isAI(stageId)) ai.push(stageId); else list.push(stageId);
      if (off.length && !quiet) toast(`Turned off ${off.map((x) => S.stage[x].title).join(' and ')}: it can't run together with ${stage.title}.`, 'info', 4500);
      S.collapsed[stageId] = false;
    }
    S.settings[enabledKey()] = list;
    S.settings[aiKey()] = ai;
  }

  function setEnabled(stageId, on) {
    applyEnabled(stageId, on);
    renderCards({ keepScroll: true });
    changed();
  }

  function syncVeOrder() {
    const ve = (S.schema.orders && S.schema.orders[S.kind]) || [];
    S.settings[veOrderKey()] = S.settings[orderKey()].filter((id) => ve.includes(id));
  }

  function moveStage(stageId, offset) {
    const order = [...S.settings[orderKey()]];
    const visible = order.filter((id) => S.stage[id] && S.stage[id].kinds.includes(S.kind));
    const i = visible.indexOf(stageId), j = i + offset;
    if (j < 0 || j >= visible.length) return;
    const a = order.indexOf(visible[i]), b = order.indexOf(visible[j]);
    [order[a], order[b]] = [order[b], order[a]];
    S.settings[orderKey()] = order;
    syncVeOrder();
    renderCards({ keepScroll: true });
    changed();
  }

  function renderCards({ keepScroll = false } = {}) {
    const wrap = $('#cards');
    const scroll = wrap.scrollTop;
    wrap.innerHTML = '';
    $('#pipelineKind').textContent = S.kind === 'video' ? 'Video' : 'Image';
    $$('#modeSwitch button').forEach((b) => b.classList.toggle('on', b.dataset.mode === S.mode));
    $('#collapseAll').hidden = S.mode === 'easy';
    wrap.classList.toggle('easy', S.mode === 'easy');
    if (S.mode === 'easy') {
      wrap.append(easyPanel(), exportCard());
      if (keepScroll) wrap.scrollTop = scroll;
      return;
    }
    const order = S.settings[orderKey()];
    const enabled = onSet();
    const visible = order.filter((id) => S.stage[id] && S.stage[id].kinds.includes(S.kind));
    visible.forEach((id, index) => wrap.append(stageCard(S.stage[id], index, visible.length, enabled.has(id), enabled)));
    wrap.append(exportCard());
    if (keepScroll) wrap.scrollTop = scroll;
  }

  function stageCard(stage, index, total, on, enabled) {
    const collapsed = S.collapsed[stage.id] ?? !on;
    const runIndex = on ? S.settings[orderKey()].filter((id) => enabled.has(id)).indexOf(stage.id) + 1 : 0;
    const ai = isAI(stage.id);
    const card = h('section', { class: `card ${on ? 'on' : ''} ${collapsed ? 'collapsed' : ''} ${ai ? 'card-ai' : ''}`, dataset: { stage: stage.id } });
    const toggleCollapse = () => { S.collapsed[stage.id] = !card.classList.contains('collapsed'); card.classList.toggle('collapsed'); store.set('collapsed', S.collapsed); };
    const need = ai ? missingFor(stage.id) : [];
    const head = h('div', { class: 'card-head' },
      h('button', { class: `switch ${on ? 'on' : ''}`, role: 'switch', 'aria-checked': on ? 'true' : 'false', 'data-tip': uiTip('card_switch') || (on ? 'Turn off' : 'Turn on'), onclick: () => setEnabled(stage.id, !on) }),
      h('div', { class: 'card-title', onclick: toggleCollapse },
        h('div', { class: 't' }, h('span', { class: 'tt', 'data-tip': stage.tip || stage.about || null, 'data-tip-title': stage.title }, stage.title),
          ai ? h('span', { class: 'badge-ai', 'data-tip': 'Runs in Visien’s own AI runtime on your GPU, before or after the Visual Enhancer stages.' }, 'AI') : null,
          on ? h('span', { class: 'pos' }, `#${runIndex}`) : null),
        on && need.length ? h('div', { class: 's s-warn' }, 'Models not installed') : h('div', { class: 's' }, on ? summaryOf(stage) : 'Off')),
      h('div', { class: 'card-tools' },
        h('button', { class: 'icon-btn', 'data-tip': uiTip('card_up') || 'Move up', html: icon('up'), disabled: index === 0, onclick: () => moveStage(stage.id, -1) }),
        h('button', { class: 'icon-btn', 'data-tip': uiTip('card_down') || 'Move down', html: icon('down'), disabled: index === total - 1, onclick: () => moveStage(stage.id, 1) }),
        h('button', { class: 'icon-btn chev-btn', 'data-tip': uiTip('card_toggle') || 'Show or hide settings', html: icon('chev'), onclick: toggleCollapse })));
    card.append(head);
    const body = h('div', { class: 'card-body' });
    if (stage.about) body.append(h('p', { class: 'card-about' }, stage.about));
    if (need.length) body.append(installNotice(need));
    if (stage.id === 'super_resolution' && Number(S.settings.vz_output_short) > 0) {
      body.append(h('div', { class: 'field-hint' }, `Size set in Easy mode: ${S.settings.vz_output_short} px on the short side, worked out for each file. `,
        h('button', { class: 'link-btn', onclick: () => { S.settings.vz_output_short = 0; renderCards({ keepScroll: true }); changed(); } }, 'Use the settings below instead')));
    }
    const fields = stage.fields.filter((f) => f.kinds.includes(S.kind));
    if (!fields.length) body.append(h('p', { class: 'field-hint' }, 'No settings for images.'));
    renderFields(body, stage, fields);
    card.append(body);
    return card;
  }

  function renderFields(body, stage, fields) {
    for (let i = 0; i < fields.length; i += 1) {
      const f = fields[i];
      if (f.type === 'tabs') {
        const seg = h('div', { class: 'seg seg-small' }, f.options.map((o) => h('button', {
          class: o.value === S.colorTab ? 'on' : '', onclick: () => { S.colorTab = o.value; renderCards({ keepScroll: true }); },
        }, o.label)));
        body.append(seg);
        continue;
      }
      if (f.type === 'heading') {
        if (f.tab && f.tab !== S.colorTab) continue;
        const id = stage ? stage.id : 'export';
        if (f.collapsible) {
          const open = Boolean(S.advanced[id]);
          body.append(h('div', { class: `field-heading collapsible ${open ? '' : 'closed'}`, html: icon('chev') + esc(f.label),
            onclick: () => { S.advanced[id] = !open; renderCards({ keepScroll: true }); } }));
        } else body.append(h('div', { class: 'field-heading' }, f.label));
        continue;
      }
      if (f.pair === 'start' && fields[i + 1] && fields[i + 1].pair === 'end') {
        const a = fieldEl(stage, f), b = fieldEl(stage, fields[i + 1]);
        const pair = h('div', { class: 'pair' }, a, b);
        if (a.classList.contains('hidden')) pair.style.display = 'none';
        body.append(pair);
        i += 1;
        continue;
      }
      body.append(fieldEl(stage, f));
    }
  }

  function fieldEl(stage, f) {
    const key = keyOf(f);
    const value = S.settings[key];
    const def = defOf(f);
    const modified = f.type !== 'vsr_mode' ? !sameValue(value, def) : value !== def;
    const disabled = (f.enabled_if && !condOK(stage, f.enabled_if)) || exportDisabled(f);
    const wrap = h('div', { class: `field ${modified ? 'modified' : ''} ${fieldVisible(stage, f) ? '' : 'hidden'} ${disabled ? 'disabled' : ''}`, dataset: { key } });
    const reset = h('button', { class: 'reset', 'data-tip': `Reset to ${typeof def === 'boolean' ? (def ? 'on' : 'off') : def === '' ? 'empty' : f.options || f.image_options ? optionLabel(f, def) : def}`, html: icon('reset'), onclick: () => setValue(key, def) });
    const label = h('span', { class: `field-label ${f.tip ? 'has-tip' : ''}`, 'data-tip': f.tip || null, 'data-tip-title': f.tip ? f.label : null }, f.label);

    if (f.type === 'slider') {
      const precision = f.precision ?? 2;
      const fmt = (v) => Number(v).toFixed(precision);
      const range = h('input', { type: 'range', min: f.min, max: f.max, step: f.step, value, 'aria-label': f.label });
      const box = h('input', { class: 'value', value: fmt(value), spellcheck: 'false', 'aria-label': `${f.label} value` });
      const paint = (v) => { range.style.setProperty('--fill', `${((v - f.min) / (f.max - f.min)) * 100}%`); };
      paint(value);
      range.addEventListener('input', () => {
        const v = f.vtype === 'int' ? Math.round(Number(range.value)) : Number(range.value);
        box.value = fmt(v); paint(v);
        S.settings[key] = v;
        wrap.classList.toggle('modified', !sameValue(v, def));
        updateCardSummary(stage);
        changed();
      });
      const commit = () => {
        let v = Number(String(box.value).replace(',', '.'));
        if (!isFinite(v)) v = S.settings[key];
        v = clamp(v, f.min, f.max);
        v = f.vtype === 'int' ? Math.round(v) : Number(v.toFixed(precision));
        setValue(key, v);
      };
      box.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); box.blur(); } if (e.key === 'Escape') { box.value = fmt(S.settings[key]); box.blur(); } });
      box.addEventListener('change', commit);
      range.addEventListener('dblclick', () => setValue(key, def));
      wrap.append(h('div', { class: 'field-row' }, label, h('span', { class: 'field-value' }, box, f.unit ? h('span', { class: 'field-hint' }, f.unit) : null, reset)), range);
    } else if (f.type === 'segment') {
      const options = optsOf(f);
      const seg = h('div', { class: 'seg' }, options.map((o) => h('button', {
        class: sameValue(o.value, value) ? 'on' : '',
        disabled: f.key === 'image_bit_depth' && o.value === 16 && !['PNG', 'TIFF'].includes(S.settings.image_format),
        onclick: () => setValue(key, o.value),
      }, o.label)));
      wrap.append(h('div', { class: 'field-row' }, label, reset), seg);
    } else if (f.type === 'select') {
      let options = optsOf(f);
      if (f.key === 'container') options = (S.schema.containers[S.settings.codec] || ['MP4']).map((c) => ({ value: c, label: c }));
      const select = h('select', { 'aria-label': f.label });
      let found = false;
      options.forEach((o, i) => {
        const opt = h('option', { value: String(i) }, o.label);
        if (sameValue(o.value, value)) { opt.selected = true; found = true; }
        select.append(opt);
      });
      if (!found) { const opt = h('option', { value: '-1', selected: true }, `Unavailable: ${value}`); select.prepend(opt); }
      select.addEventListener('change', () => { const o = options[Number(select.value)]; if (o) setValue(key, o.value); });
      wrap.append(h('div', { class: 'field-row' }, label, reset), select);
    } else if (f.type === 'toggle') {
      const sw = h('button', { class: `switch ${value ? 'on' : ''}`, role: 'switch', 'aria-checked': value ? 'true' : 'false', 'aria-label': f.label, onclick: () => setValue(key, !value) });
      wrap.append(h('div', { class: 'toggle-row' }, label, reset, sw));
      if (f.hint) wrap.append(h('div', { class: 'field-hint' }, f.hint));
    } else if (f.type === 'number') {
      const derived = lockedHeight(f);
      const input = h('input', { class: 'input mono', type: 'number', min: f.min, max: f.max, step: 1, value: derived ?? value, 'aria-label': f.label });
      input.addEventListener('change', () => { let v = Math.round(Number(input.value)); if (!isFinite(v)) v = def; setValue(key, clamp(v, f.min, f.max)); });
      wrap.append(h('div', { class: 'field-row' }, label, reset), input);
    } else if (f.type === 'path') {
      const input = h('input', { class: 'input', value: value || '', placeholder: f.folder ? 'No folder' : 'No file chosen', spellcheck: 'false' });
      input.addEventListener('change', () => setValue(key, input.value.trim().replace(/^"|"$/g, '')));
      const browse = h('button', { class: 'btn btn-quiet btn-sm', onclick: async () => {
        const picked = f.folder ? await pickFolder(value || '') : await pickFile(f.filter);
        if (picked) setValue(key, picked);
      } }, 'Browse');
      wrap.append(h('div', { class: 'field-row' }, label, reset), h('div', { class: 'path-row' }, input, browse));
    } else if (f.type === 'text') {
      const input = h('input', { class: 'input', value: value ?? '', maxlength: 60, spellcheck: 'false', 'aria-label': f.label });
      input.addEventListener('change', () => setValue(key, input.value.trim() || def));
      wrap.append(h('div', { class: 'field-row' }, label, reset), input);
    } else if (f.type === 'fps') {
      const listId = `dl-${key}`;
      const input = h('input', { class: 'input mono', value, list: listId, inputmode: 'decimal', spellcheck: 'false', 'aria-label': f.label });
      const datalist = h('datalist', { id: listId }, (f.suggestions || []).map((s) => h('option', { value: s })));
      input.addEventListener('change', () => {
        const text = input.value.trim().replace(',', '.');
        const n = Number(text);
        if (!isFinite(n) || n <= 0 || n > 1000) { toast('Enter a frame rate between 1 and 1000.', 'err'); input.value = S.settings[key]; return; }
        setValue(key, text);
      });
      wrap.append(h('div', { class: 'field-row' }, label, reset), input, datalist);
    } else if (f.type === 'vsr_mode') {
      const families = vsrFamilies(f);
      const famIndex = value < 8 ? 0 : value < 12 ? 1 : value < 16 ? 2 : 3;
      const famSelect = h('select', { 'aria-label': 'Mode family' }, families.map((fam, i) => h('option', { value: i, selected: i === famIndex }, fam.label)));
      const levelSelect = h('select', { 'aria-label': 'Quality' }, families[famIndex].levels.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));
      famSelect.addEventListener('change', () => {
        const next = Number(famSelect.value);
        const base = [0, 8, 12, 16];
        const level = famIndex === 0 ? Math.max(0, value - 1) : value - base[famIndex];
        setValue(key, base[next] + Math.min(3, level) + (next === 0 ? 1 : 0));
      });
      levelSelect.addEventListener('change', () => setValue(key, Number(levelSelect.value)));
      wrap.append(h('div', { class: 'field-row' }, label, reset), h('div', { class: 'pair' }, famSelect, levelSelect));
      if (value >= 8 && value <= 15) wrap.append(h('div', { class: 'field-hint' }, 'Denoise and deblur keep the input size.'));
    }
    if (f.key === 'quality' && S.schema && f.hide_for_codec && f.hide_for_codec.includes(S.settings.codec)) wrap.classList.add('hidden');
    return wrap;
  }

  function exportDisabled(f) {
    if (f.key === 'hdr_mode') return String(S.settings.codec || '').startsWith('H.264');
    return false;
  }

  function updateCardSummary(stage) {
    if (!stage) return;
    const node = $(`.card[data-stage="${stage.id}"] .card-title .s`);
    if (node && onSet().has(stage.id)) node.textContent = summaryOf(stage);
  }

  function exportCard() {
    const card = h('section', { class: 'card card-export on' });
    card.append(h('div', { class: 'card-head' }, h('div', { class: 'card-title' },
      h('div', { class: 't' }, h('span', { class: 'tt', 'data-tip': S.schema.export_tip || null, 'data-tip-title': 'Export Settings' }, 'Export Settings')), h('div', { class: 's' }, exportSummary()))));
    const body = h('div', { class: 'card-body' });
    const fields = S.schema.export.filter((f) => f.kinds.includes(S.kind));
    renderFields(body, null, fields);
    if (S.kind === 'video' && S.schema.export.find((f) => f.key === 'quality').hide_for_codec.includes(S.settings.codec)) {
      body.append(h('div', { class: 'field-hint' }, 'Encoding quality: fixed by the codec.'));
    }
    body.append(planBox());
    card.append(body);
    return card;
  }

  function exportSummary() {
    const cmp = S.settings.vz_compare === 'stack' ? ' · + comparison ↕' : S.settings.vz_compare === 'side' ? ' · + comparison ↔' : '';
    if (S.kind === 'video') return `${S.settings.codec} · ${S.settings.container} · ${optionLabel(S.schema.export.find((f) => f.key === 'quality'), S.settings.quality)}${S.settings.hdr_mode ? ' · HDR' : ''}${cmp}`;
    return `${S.settings.image_format} · ${S.settings.image_bit_depth}-bit${cmp}`;
  }

  function planBox() {
    const box = h('div', { class: 'plan', id: 'planBox' });
    fillPlan(box);
    return box;
  }

  function fillPlan(box = $('#planBox')) {
    if (!box) return;
    box.innerHTML = '';
    const m = activeMedia();
    const plan = S.plan;
    if (!m) { box.append(h('div', { class: 'plan-note' }, 'Select a file to see the output size.')); return; }
    if (m.kind !== S.kind) { box.append(h('div', { class: 'plan-note' }, `The selected file is ${m.kind === 'video' ? 'a video' : 'an image'}. Switch to the ${m.kind === 'video' ? 'Video' : 'Image'} pipeline to see its output.`)); return; }
    const source = `${fmtSize(m.width, m.height)}${m.kind === 'video' ? ' · ' + fmtFps(m.fps_value) : ''}`;
    if (!plan) { box.append(h('div', { class: 'plan-line' }, h('b', {}, source), h('span', { class: 'arrow' }, '→'), h('span', {}, '…'))); return; }
    if (!plan.ok) {
      box.append(h('div', { class: 'plan-line' }, h('b', {}, source), h('span', { class: 'arrow' }, '→'), h('span', { style: 'color:var(--err)' }, 'not possible')));
      return;
    }
    const out = `${fmtSize(plan.width, plan.height)}${m.kind === 'video' ? ' · ' + fmtFps(plan.fps) : ''}${plan.hdr ? ' · HDR' : ''}`;
    box.append(h('div', { class: 'plan-line' }, h('span', {}, source), h('span', { class: 'arrow' }, '→'), h('b', {}, out)));
    const chips = (plan.stages || []).filter((s) => s !== 'export').map((s) => h('span', { class: 'chip' }, (S.stage[s] && S.stage[s].short) || s));
    if (chips.length) box.append(h('div', { class: 'plan-stages' }, chips));
    if (plan.estimated) box.append(h('div', { class: 'plan-note' }, 'Estimated by Visien. Connect Visual Enhancer for its exact plan.'));
  }

  function renderChecks() {
    const node = $('#checks');
    node.innerHTML = '';
    const { problems, warnings } = S.checks;
    problems.forEach((t) => node.append(h('div', { class: 'check-item err', html: icon('alert') + `<span>${esc(t)}</span>` })));
    warnings.forEach((t) => node.append(h('div', { class: 'check-item warn', html: icon('alert') + `<span>${esc(t)}</span>` })));
  }

  let planSeq = 0;
  async function refreshPlan() {
    const seq = ++planSeq;
    const m = activeMedia();
    try {
      const result = await api('/plan', { media_id: m && m.kind === S.kind ? m.id : null, kind: S.kind, settings: S.settings });
      if (seq !== planSeq) return;
      S.plan = result.plan || null;
      S.checks = { problems: result.problems || [], warnings: result.warnings || [] };
    } catch (error) {
      if (seq !== planSeq) return;
      S.plan = null;
      S.checks = { problems: [error.message], warnings: [] };
    }
    fillPlan();
    renderChecks();
    updateRenderButton();
  }

  // ---------------------------------------------------------------- AI models

  const comp = (id) => ((S.models && S.models.components) || []).find((c) => c.id === id) || null;
  const compReady = (id) => Boolean(comp(id) && comp(id).installed);
  const compByFile = (name) => ((S.models && S.models.components) || []).find((c) => c.file && c.file.split('/').pop() === name) || null;
  const accepted = (id) => ((S.models && S.models.accepted) || []).includes(id);

  // Components a stage needs with the current settings (mirrors models.required on the server).
  function neededFor(stageId, settings = S.settings) {
    if (!S.models) return [];
    const ids = ['runtime'];
    if (stageId === 'seedvr2') ids.push('seedvr2_vae', (compByFile(settings.seedvr2_model) || { id: 'seedvr2_3b_fp8' }).id);
    else if (stageId === 'rife') ids.push((compByFile(settings.rife_model) || { id: 'rife426' }).id);
    else if (stageId === 'face_restore') ids.push('yunet', settings.face_model === 'codeformer' ? 'codeformer' : 'gfpgan');
    else return [];
    return ids;
  }
  const missingFor = (stageId, settings = S.settings) => neededFor(stageId, settings).filter((id) => !compReady(id));
  const sizeOf = (ids) => ids.reduce((sum, id) => sum + ((comp(id) || {}).size || 0), 0);
  const installing = (ids) => ids.some((id) => { const c = comp(id); return c && c.job && ['queued', 'downloading', 'installing'].includes(c.job.state); });

  function installNotice(ids) {
    const busy = installing(ids);
    const names = ids.map((id) => (comp(id) || { title: id }).title).join(', ');
    const job = ids.map((id) => comp(id)).find((c) => c && c.job && ['downloading', 'installing'].includes(c.job.state));
    return h('div', { class: 'need-models' },
      h('span', { html: icon(busy ? 'refresh' : 'alert') }),
      h('div', { class: 'nm-text' }, busy ? `Installing ${names}…` : `Needs ${names} · ${fmtBytes(sizeOf(ids))}`,
        busy && job ? h('div', { class: 'bar' }, h('i', { style: `width:${Math.round((job.job.progress || 0) * 100)}%` })) : null),
      busy ? null : h('button', { class: 'btn btn-sm', 'data-tip': 'Downloads the files from their official sources into the Visien folder.', onclick: (e) => { e.stopPropagation(); installModels(ids); } }, 'Install'));
  }

  async function loadModels() {
    try { S.models = await api('/models'); } catch { S.models = null; }
    return S.models;
  }

  async function installModels(ids) {
    ids = [...new Set(ids)];
    const needAccept = ids.filter((id) => comp(id) && comp(id).accept && !accepted(id));
    let accept = false;
    if (needAccept.length) {
      const c = comp(needAccept[0]);
      accept = await confirmModal(`${c.title} licence`, `${c.title} is released under the ${c.license}. ` +
        'You may use it for personal, research and other non-commercial work only. For client or commercial work, use GFPGAN 1.4 (Apache 2.0) instead. Install it?', 'Accept and install');
      if (!accept) return;
    }
    const big = sizeOf(ids.filter((id) => !compReady(id)));
    if (big > 2e9 && !(await confirmModal('Download AI models', `This downloads about ${fmtBytes(big)} into the Visien folder. It can take a while; you can keep working meanwhile.`, 'Download'))) return;
    try {
      S.models = await api('/models/install', { ids, accept_licence: accept });
      toast('Installing in the background. Progress is shown on the card and in Settings › AI models.', 'info', 4500);
      renderCards({ keepScroll: true });
      watchModels();
    } catch (error) { fail(error); }
  }

  let modelsTimer = 0;
  const modelListeners = new Set();
  const toldErrors = new Set();
  function watchModels() {
    clearTimeout(modelsTimer);
    modelsTimer = setTimeout(async () => {
      const wasBusy = S.models && S.models.busy;
      const before = stable(((S.models && S.models.components) || []).map((c) => [c.id, c.installed, c.job && c.job.state]));
      await loadModels();
      if (!S.models) return;
      const after = stable(S.models.components.map((c) => [c.id, c.installed, c.job && c.job.state]));
      modelListeners.forEach((fn) => fn());
      if (before !== after) {
        renderCards({ keepScroll: true });
        refreshPlan();
        S.models.components.filter((c) => c.job && c.job.state === 'error' && !toldErrors.has(c.id + c.job.error))
          .forEach((c) => { toldErrors.add(c.id + c.job.error); toast(`${c.title}: ${c.job.error}`, 'err'); });
      } else if (S.models.busy) {
        // progress only: refresh install bars without a full redraw
        $$('.need-models .bar i').forEach((bar) => {
          const job = S.models.components.find((c) => c.job && ['downloading', 'installing'].includes(c.job.state));
          if (job) bar.style.width = `${Math.round((job.job.progress || 0) * 100)}%`;
        });
      }
      if (S.models.busy) watchModels();
      else if (wasBusy) toast('AI models are ready.', 'ok', 3000);
    }, 1200);
  }

  // ---------------------------------------------------------------- easy mode

  const SEEDVR2_FAST = 'seedvr2_ema_3b_fp8_e4m3fn.safetensors';
  const SEEDVR2_DETAIL = 'seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors';
  const SEEDVR2_DETAIL_ALT = 'seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors';
  const upKey = (base) => (S.kind === 'image' ? base.replace('upscale_', 'upscale_image_') : base);
  const round05 = (v) => Math.round(v * 20) / 20;

  function easyState() {
    const st = S.settings, on = onSet();
    const fps = (v) => String(Math.round(parseFloat(v) || 0));
    let size = 'custom';
    if (!on.has('super_resolution')) size = 'same';
    else if (Number(st.vz_output_short) === 1080) size = '1080';
    else if (Number(st.vz_output_short) === 2160) size = '2160';
    else if (!Number(st.vz_output_short) && st[upKey('upscale_size_mode')] === 'Scale factor' && Number(st[upKey('upscale_scale_factor')]) === 2) size = '2x';
    let motion = 'off';
    if (on.has('rife')) motion = st.rife_mode === 'Target FPS' ? fps(st.rife_target_fps) : 'custom';
    else if (on.has('vfx_frame_generation')) motion = st.vfx_frame_rate_mode === 'Target FPS' ? fps(st.vfx_target_fps) : 'custom';
    else if (on.has('frame_generation') || on.has('fsr_frame_generation')) motion = 'custom';
    if (!['off', '48', '60', 'custom'].includes(motion)) motion = 'custom';
    return {
      realism: on.has('neural_model') ? clamp(Math.round((Number(st.nr_intensity) - 0.4) / 0.012), 1, 100) : 0,
      restore: on.has('seedvr2') ? (/_7b_/.test(st.seedvr2_model) ? 'detail' : 'fast') : 'off',
      size, motion,
      detail: on.has('cas_sharpening') ? Number(st.cas_sharpness) : 0,
      grain: on.has('grain') ? Number(st.grain_amount) : 0,
      faces: on.has('face_restore') ? (Number(st.face_blend) >= 70 ? 'strong' : 'natural') : 'off',
      colors: on.has('color_match') ? Number(st.color_match_strength) : 0,
    };
  }

  const rifeReady = () => compReady('runtime') && ['rife426', 'rife417', 'rife49'].some(compReady);
  const codeformerReady = () => compReady('codeformer') && accepted('codeformer');

  function setEasy(id, value) {
    const st = S.settings;
    if (id === 'realism') {
      applyEnabled('neural_model', value > 0, true);
      if (value > 0) st.nr_intensity = round05(0.4 + value * 0.012);
    } else if (id === 'restore') {
      applyEnabled('seedvr2', value !== 'off', true);
      if (value !== 'off') {
        st.seedvr2_model = value === 'fast' ? SEEDVR2_FAST : (!compReady('seedvr2_7b_sharp_fp8') && compReady('seedvr2_7b_fp8') ? SEEDVR2_DETAIL_ALT : SEEDVR2_DETAIL);
        Object.assign(st, { seedvr2_size_mode: 'min', seedvr2_short_side: 1080, seedvr2_color: 'lab', seedvr2_blend: 100,
          seedvr2_blocks_to_swap: value === 'detail' ? 16 : 0, seedvr2_vae_tiling: true });
      }
    } else if (id === 'size') {
      applyEnabled('super_resolution', value !== 'same', true);
      st.vz_output_short = ['1080', '2160'].includes(value) ? Number(value) : 0;
      if (value !== 'same') st[upKey('upscale_vsr_quality')] = 4;
      if (value === '2x') { st[upKey('upscale_size_mode')] = 'Scale factor'; st[upKey('upscale_scale_factor')] = 2.0; }
    } else if (id === 'detail') {
      applyEnabled('cas_sharpening', value > 0, true);
      if (value > 0) st.cas_sharpness = value;
    } else if (id === 'grain') {
      applyEnabled('grain', value > 0, true);
      if (value > 0) { st.grain_amount = value; if (S.kind === 'video') st.grain_animated = true; }
    } else if (id === 'motion') {
      ['rife', 'vfx_frame_generation', 'frame_generation', 'fsr_frame_generation'].forEach((x) => applyEnabled(x, false, true));
      if (value !== 'off') {
        if (rifeReady()) {
          applyEnabled('rife', true, true);
          Object.assign(st, { rife_mode: 'Target FPS', rife_target_fps: value, rife_scene_detect: true });
        } else {
          applyEnabled('vfx_frame_generation', true, true);
          Object.assign(st, { vfx_frame_rate_mode: 'Target FPS', vfx_target_fps: value, vfx_automatic_shot_detection: true });
        }
      }
    } else if (id === 'colors') {
      applyEnabled('color_match', value > 0, true);
      if (value > 0) Object.assign(st, { color_match_strength: value, color_match_scale: st.color_match_scale || 'balanced' });
    } else if (id === 'faces') {
      applyEnabled('face_restore', value !== 'off', true);
      if (value !== 'off') {
        // GFPGAN unless the preset already chose CodeFormer (its licence is non-commercial only)
        const model = st.face_model === 'codeformer' && codeformerReady() ? 'codeformer' : 'gfpgan';
        const strong = value === 'strong';
        Object.assign(st, { face_model: model, face_fidelity: strong ? 0.5 : 0.7,
          face_blend: model === 'codeformer' ? (strong ? 80 : 50) : (strong ? 75 : 45), face_which: 'all', face_smoothing: 60 });
      }
    }
    renderCards({ keepScroll: true });
    changed();
  }

  function easyPanel() {
    const wrap = h('div', { class: 'easy-wrap' });
    const preset = S.presets.find((p) => p.id === S.presetId);
    const modified = isModified();
    wrap.append(h('div', { class: 'easy-preset' },
      h('div', { class: 'ep-top' }, h('span', { class: 'ep-label' }, 'Preset'), h('b', {}, S.presetName || 'Custom'),
        modified ? h('span', { class: 'ep-mod', 'data-tip': 'Changed since the preset was loaded. Save it from the preset menu.' }, 'edited') : null,
        h('span', { class: 'grow' }),
        h('button', { class: 'link-btn', 'data-tip': 'Choose another ready-made preset.', onclick: (e) => { e.stopPropagation(); openPresetMenu(); } }, 'Change')),
      preset && preset.description ? h('p', { class: 'ep-desc' }, preset.description) : null));

    const state = easyState();
    const box = h('div', { class: 'easy-controls' });
    (S.schema.easy || []).forEach((c) => {
      if (c.kinds && !c.kinds.includes(S.kind)) return;
      const value = state[c.id];
      const row = h('div', { class: 'easy-row' });
      const label = h('span', { class: 'field-label has-tip', 'data-tip': c.tip, 'data-tip-title': c.label }, c.label);
      if (c.type === 'slider') {
        const out = h('span', { class: 'mono easy-value' }, value > 0 ? String(value) : 'Off');
        const range = h('input', { type: 'range', min: c.min, max: c.max, step: 1, value, 'aria-label': c.label });
        const paint = (v) => range.style.setProperty('--fill', `${((v - c.min) / (c.max - c.min)) * 100}%`);
        paint(value);
        range.addEventListener('input', () => { const v = Number(range.value); out.textContent = v > 0 ? String(v) : 'Off'; paint(v); });
        range.addEventListener('change', () => setEasy(c.id, Number(range.value)));
        row.append(h('div', { class: 'field-row' }, label, out), range);
      } else {
        const seg = h('div', { class: 'seg' }, c.options.map((o) => h('button', { class: value === o.value ? 'on' : '', onclick: () => setEasy(c.id, o.value) }, o.label)));
        row.append(h('div', { class: 'field-row' }, label, value === 'custom' ? h('span', { class: 'field-hint', 'data-tip': 'Set in Advanced mode. Pick an option here to replace it.' }, 'custom') : null), seg);
      }
      // notes and model installs right under the control
      const stageFor = { restore: 'seedvr2', faces: 'face_restore', motion: 'rife', colors: 'color_match' }[c.id];
      if (stageFor && value !== 'off' && value !== 0 && value !== 'custom' && onSet().has(stageFor)) {
        const need = missingFor(stageFor);
        if (need.length) row.append(installNotice(need));
      }
      if (c.id === 'motion' && value !== 'off' && onSet().has('vfx_frame_generation') && S.models && !rifeReady()) {
        row.append(h('div', { class: 'field-hint' }, 'Using NVIDIA frame generation. ',
          h('button', { class: 'link-btn', onclick: () => installModels(['runtime', 'rife426']) }, 'Install RIFE'), ' for interpolation on any NVIDIA GPU.'));
      }
      if (c.id === 'faces' && value !== 'off') {
        row.append(h('div', { class: 'field-hint' }, S.settings.face_model === 'codeformer'
          ? 'Using CodeFormer: licensed for non-commercial use only. Pick “Realism · Faces” or GFPGAN in Advanced for client work.'
          : 'Using GFPGAN 1.4 (commercial use allowed).'));
      }
      if (c.id === 'restore' && value !== 'off') {
        row.append(h('div', { class: 'field-hint' }, value === 'detail' ? 'SeedVR2 7B: best detail, about 3× slower than Fast.' : 'SeedVR2 3B: removes AI softness and compression. Slow; preview a few seconds first.'));
      }
      box.append(row);
    });
    wrap.append(box);

    const order = S.settings[orderKey()].filter((id) => onSet().has(id) && S.stage[id] && S.stage[id].kinds.includes(S.kind));
    wrap.append(h('div', { class: 'easy-chain' },
      h('span', { class: 'ep-label', 'data-tip': 'The stages that run, in order. Switch to Advanced to change any of them.' }, 'Runs'),
      order.length ? order.flatMap((id, i) => [i ? h('span', { class: 'arrow' }, '›') : null,
        h('span', { class: `chip ${isAI(id) ? 'chip-ai' : ''}`, 'data-tip': S.stage[id].tip || null, 'data-tip-title': S.stage[id].title }, S.stage[id].short || S.stage[id].title)]) : h('span', { class: 'field-hint' }, 'Nothing is on.'),
      h('button', { class: 'link-btn', 'data-tip': 'Switches to Advanced mode with every stage and setting.', onclick: () => setPipelineMode('advanced') }, 'All settings')));
    return wrap;
  }

  function setPipelineMode(mode) {
    S.mode = mode;
    store.set('mode', mode);
    renderCards();
  }

  // ---------------------------------------------------------------- tooltips

  const tipBox = h('div', { class: 'tip', role: 'tooltip' });
  let tipTimer = 0, tipTarget = null;
  function hideTip() { clearTimeout(tipTimer); tipTarget = null; tipBox.classList.remove('show'); }
  function showTip(el) {
    if (!el.isConnected || !el.dataset.tip) return;
    tipBox.innerHTML = '';
    if (el.dataset.tipTitle) tipBox.append(h('b', {}, el.dataset.tipTitle));
    tipBox.append(h('span', {}, el.dataset.tip));
    tipBox.style.left = '0px'; tipBox.style.top = '0px';
    tipBox.classList.add('show');
    const r = el.getBoundingClientRect(), t = tipBox.getBoundingClientRect();
    const below = r.bottom + 8 + t.height < window.innerHeight - 6;
    const left = clamp(r.left + r.width / 2 - t.width / 2, 8, window.innerWidth - t.width - 8);
    tipBox.style.left = `${left}px`;
    tipBox.style.top = `${below ? r.bottom + 8 : Math.max(6, r.top - t.height - 8)}px`;
  }
  function bindTips() {
    document.body.append(tipBox);
    document.addEventListener('mouseover', (e) => {
      const el = e.target.closest ? e.target.closest('[data-tip], [title]') : null;
      if (el === tipTarget) return;
      hideTip();
      if (!el || el.closest('.tip')) return;
      if (el.hasAttribute('title')) {
        const text = el.getAttribute('title');
        el.removeAttribute('title');
        if (text && !el.dataset.tip) el.dataset.tip = text;
      }
      if (!el.dataset.tip) return;
      tipTarget = el;
      tipTimer = setTimeout(() => showTip(el), 420);
    });
    document.addEventListener('mousedown', hideTip, true);
    document.addEventListener('keydown', hideTip, true);
    document.addEventListener('scroll', hideTip, true);
    window.addEventListener('blur', hideTip);
  }

  // Static controls get their (longer) explanations from the server's tip table.
  function applyUiTips() {
    const map = {
      '#kindSwitch': 'kind', '#presetButton': 'preset', '#enginePill': 'engine', '#settingsButton': 'settings',
      '#addMedia': 'add', '#addFolder': 'folder', '.media-tools .check': 'render_all', '#removeMedia': 'remove',
      '#viewModes [data-mode="split"]': 'split', '#viewModes [data-mode="side"]': 'side', '#viewModes [data-mode="stack"]': 'stack', '#viewModes [data-mode="source"]': 'source',
      '#viewModes [data-mode="output"]': 'output', '#losslessToggle': 'lossless', '#zoomFit': 'fit', '#zoom100': 'zoom100',
      '#playButton': 'play', '#stepBack': 'prev', '#stepFwd': 'next', '#previewButton': 'preview', '#previewLength': 'preview_length',
      '#previewAgain': 'preview_again', '#openOutput': 'open_output', '#renderButton': 'render', '#queueStart': 'queue_start',
      '#queueStop': 'queue_stop', '#queueClear': 'queue_clear', '#queueLog': 'queue_log', '#collapseAll': 'collapse',
      '#modeSwitch [data-mode="easy"]': 'mode_easy', '#modeSwitch [data-mode="advanced"]': 'mode_advanced',
    };
    Object.entries(map).forEach(([sel, key]) => {
      const text = uiTip(key);
      $$(sel).forEach((el) => { if (text) { el.removeAttribute('title'); el.dataset.tip = text; } });
    });
  }

  // ---------------------------------------------------------------- media list

  function mediaInfoLine(m) {
    if (m.kind === 'video') return [fmtSize(m.width, m.height), fmtFps(m.fps_value), fmtDuration(m.duration), (m.codec || '').toUpperCase(), m.hdr ? 'HDR' : ''].filter(Boolean).join(' · ');
    return [fmtSize(m.width, m.height), (m.codec || '').toUpperCase(), fmtBytes(m.size)].filter(Boolean).join(' · ');
  }

  function renderMedia() {
    const list = $('#mediaList');
    list.innerHTML = '';
    S.picked = new Set([...S.picked].filter((id) => S.media.some((m) => m.id === id)));
    $('#mediaCount').textContent = S.media.length ? String(S.media.length) : '';
    $('#mediaEmpty').hidden = S.media.length > 0;
    list.hidden = S.media.length === 0;
    $('#mediaTools').hidden = S.media.length === 0;
    $('#selectAll').checked = S.media.length > 0 && S.picked.size === S.media.length;
    for (const m of S.media) {
      const picked = S.picked.has(m.id);
      const item = h('li', { class: `media-item ${m.id === S.activeId ? 'active' : ''} ${m.missing ? 'missing' : ''}`, title: m.path, dataset: { id: m.id } },
        h('span', { class: `pick ${picked ? 'on' : ''}`, role: 'checkbox', 'aria-checked': picked ? 'true' : 'false', title: 'Include in render', tabindex: 0 }),
        h('span', { class: 'thumb', style: m.missing ? '' : `background-image:url('/api/media/${m.id}/thumb')` }, h('span', { class: 'badge' }, m.kind === 'video' ? fmtDuration(m.duration) || 'VID' : 'IMG')),
        h('span', { class: 'meta' }, h('div', { class: 'name' }, m.name), h('div', { class: 'info' }, m.missing ? 'File missing' : mediaInfoLine(m))));
      item.querySelector('.pick').addEventListener('click', (e) => {
        e.stopPropagation();
        if (S.picked.has(m.id)) S.picked.delete(m.id); else S.picked.add(m.id);
        store.set('picked', [...S.picked]);
        renderMedia(); updateRenderButton();
      });
      item.addEventListener('click', () => activate(m.id));
      list.append(item);
    }
    store.set('picked', [...S.picked]);
    updateRenderButton();
  }

  function activate(id) {
    const m = S.media.find((x) => x.id === id);
    if (!m) return;
    const switched = S.activeId !== id;
    S.activeId = id;
    store.set('activeId', id);
    if (switched) {
      stopPlayback();
      S.preview = null; S.previewOn = false; S.previewJob = null; S.time = 0;
      S.view.zoom = null; S.view.cx = 0.5; S.view.cy = 0.5; S.view.split = 0.5;
    }
    if (m.kind !== S.kind) setKind(m.kind, { quiet: true });
    $$('.media-item').forEach((n) => n.classList.toggle('active', n.dataset.id === id));
    renderCards({ keepScroll: true });
    buildViewer();
    renderTimeline();
    S.plan = null; fillPlan(); changed();
  }

  async function removeMedia() {
    const ids = S.picked.size ? [...S.picked] : S.activeId ? [S.activeId] : [];
    if (!ids.length) return;
    try {
      S.media = await api('/media/remove', { ids });
      ids.forEach((id) => S.picked.delete(id));
      if (!activeMedia()) { S.activeId = S.media.length ? S.media[0].id : null; S.preview = null; S.previewOn = false; }
      renderMedia();
      if (S.activeId) activate(S.activeId); else { buildViewer(); renderTimeline(); changed(); }
    } catch (error) { fail(error); }
  }

  // ---------------------------------------------------------------- kind switch

  function setKind(kind, { quiet = false } = {}) {
    if (kind === S.kind) return;
    S.kind = kind;
    store.set('kind', kind);
    $$('#kindSwitch button').forEach((b) => b.classList.toggle('on', b.dataset.kind === kind));
    renderCards();
    if (!quiet) { S.plan = null; changed(); buildViewer(); renderTimeline(); }
  }

  // ---------------------------------------------------------------- viewer

  const V = { a: null, b: null, stillA: null, stillB: null, contentW: 1, contentH: 1, raf: 0, frameSeq: 0, frameTimer: 0 };

  function hasOutput() { return Boolean(S.previewOn && S.preview); }

  function buildViewer() {
    const m = activeMedia();
    const viewer = $('#viewer');
    const frameA = $('#frameA'), frameB = $('#frameB');
    frameA.innerHTML = ''; frameB.innerHTML = '';
    V.a = V.b = V.stillA = V.stillB = null;
    viewer.classList.toggle('has-output', hasOutput());
    renderEmpty();
    if (!m || (S.engine && !S.engine.ok && !S.media.length)) { V.contentW = 16; V.contentH = 9; updateLabels(); applyMode(); renderViewerStatus(); return; }
    if (hasOutput()) {
      const p = S.preview;
      V.contentW = p.output.width; V.contentH = p.output.height;
      if (p.kind === 'video') {
        V.a = makeVideo(`/api/preview-files/${p.key}/source`);
        V.b = makeVideo(`/api/preview-files/${p.key}/output`);
        V.stillA = h('img', { alt: '', hidden: true }); V.stillB = h('img', { alt: '', hidden: true });
        frameA.append(V.a, V.stillA); frameB.append(V.b, V.stillB);
        V.b.addEventListener('loadedmetadata', () => { seekPreview((S.time - p.start) || 0); });
        V.b.addEventListener('timeupdate', () => { if (S.playing) { S.time = p.start + V.b.currentTime; renderTimeline(); } });
        if (S.view.lossless) showStills();
      } else {
        V.a = h('img', { alt: 'Source', src: `/api/preview-files/${p.key}/source` });
        V.b = h('img', { alt: 'Visien output', src: `/api/preview-files/${p.key}/output` });
        frameA.append(V.a); frameB.append(V.b);
      }
    } else {
      V.contentW = m.width || 16; V.contentH = m.height || 9;
      V.a = h('img', { alt: 'Source' });
      frameA.append(V.a);
      loadSourceFrame(true);
    }
    updateLabels();
    applyMode();
    layoutViewer();
    renderViewerStatus();
  }

  function makeVideo(src) {
    const v = document.createElement('video');
    v.src = src; v.muted = true; v.loop = true; v.playsInline = true; v.preload = 'auto';
    v.disablePictureInPicture = true;
    return v;
  }

  function loadSourceFrame(immediate = false) {
    const m = activeMedia();
    if (!m || hasOutput() || !V.a) return;
    clearTimeout(V.frameTimer);
    const run = () => {
      const seq = ++V.frameSeq;
      const src = m.kind === 'image' ? (/\.(png|jpe?g|webp|avif|gif|bmp)$/i.test(m.path) ? `/api/media/${m.id}/file` : `/api/media/${m.id}/frame`)
        : `/api/media/${m.id}/frame?t=${S.time.toFixed(3)}`;
      const img = new Image();
      img.onload = () => { if (seq === V.frameSeq && V.a && !hasOutput()) V.a.src = img.src; };
      img.onerror = () => { if (seq === V.frameSeq) toast(`Could not read a frame from ${m.name}.`, 'err'); };
      img.src = src;
    };
    if (immediate) run(); else V.frameTimer = setTimeout(run, 90);
  }

  function applyMode() {
    const viewer = $('#viewer');
    ['split', 'side', 'stack', 'source', 'output'].forEach((mode) => viewer.classList.toggle(`mode-${mode}`, S.view.mode === mode));
    $$('#viewModes button').forEach((b) => b.classList.toggle('on', b.dataset.mode === S.view.mode));
    const noOut = !hasOutput();
    $$('#viewModes button').forEach((b) => { b.disabled = noOut && b.dataset.mode !== 'source'; });
    if (noOut) { viewer.classList.remove('mode-split', 'mode-side', 'mode-stack', 'mode-output'); viewer.classList.add('mode-source'); }
    $('#losslessToggle').classList.toggle('on', S.view.lossless);
    $('#losslessToggle').disabled = !(hasOutput() && S.preview.kind === 'video');
    updateLabels();
    layoutViewer();
  }

  function updateLabels() {
    const m = activeMedia();
    const left = $('#labelSource'), right = $('#labelOutput');
    if (!m) { left.innerHTML = ''; right.innerHTML = ''; return; }
    if (hasOutput()) {
      const p = S.preview;
      left.innerHTML = `Source<span class="mono">${fmtSize(p.source.width, p.source.height)}</span>`;
      right.innerHTML = `Visien<span class="mono">${fmtSize(p.output.width, p.output.height)}${p.kind === 'video' ? ' · ' + fmtFps(p.output.fps) : ''}</span>`;
      if (S.view.mode === 'source') right.innerHTML = '';
      if (S.view.mode === 'output') left.innerHTML = '';
    } else {
      left.innerHTML = `Source<span class="mono">${fmtSize(m.width, m.height)}</span>`;
      right.innerHTML = '';
    }
  }

  function paneRects() {
    const viewer = $('#viewer');
    const W = viewer.clientWidth, H = viewer.clientHeight;
    if (S.view.mode === 'side' && hasOutput()) return { a: [W / 2, H], b: [W / 2, H] };
    if (S.view.mode === 'stack' && hasOutput()) return { a: [W, H / 2], b: [W, H / 2] };
    return { a: [W, H], b: [W, H] };
  }

  function fitZoom() {
    const { a } = paneRects();
    return Math.min(a[0] / V.contentW, a[1] / V.contentH) || 1;
  }

  function layoutViewer() {
    const z = S.view.zoom || fitZoom();
    const rects = paneRects();
    const place = (frame, [pw, ph]) => {
      const left = pw / 2 - S.view.cx * V.contentW * z;
      const top = ph / 2 - S.view.cy * V.contentH * z;
      frame.style.width = `${V.contentW}px`; frame.style.height = `${V.contentH}px`;
      frame.style.transform = `translate(${left}px, ${top}px) scale(${z})`;
      frame.classList.toggle('pixelated', z * devicePixelRatio >= 2);
    };
    place($('#frameA'), rects.a);
    place($('#frameB'), rects.b);
    const viewer = $('#viewer');
    const paneB = $('#paneB');
    if (S.view.mode === 'split' && hasOutput()) {
      const x = S.view.split * viewer.clientWidth;
      paneB.style.clipPath = `inset(0 0 0 ${x}px)`;
      $('#divider').style.left = `${x}px`;
    } else paneB.style.clipPath = '';
    const pct = Math.round(z * devicePixelRatio * 100);
    $('#zoomReadout').textContent = !activeMedia() ? '' : S.view.zoom ? `${pct}%` : `Fit · ${pct}%`;
  }

  function zoomAt(factor, clientX, clientY) {
    const viewer = $('#viewer');
    const rect = viewer.getBoundingClientRect();
    const z = S.view.zoom || fitZoom();
    const nz = clamp(z * factor, Math.min(fitZoom(), 0.05), 32 / devicePixelRatio);
    let px = clientX - rect.left, py = clientY - rect.top;
    let pw = rect.width;
    if (S.view.mode === 'side' && hasOutput()) { pw = rect.width / 2; if (px > pw) px -= pw; }
    let ph = rect.height;
    if (S.view.mode === 'stack' && hasOutput()) { ph = rect.height / 2; if (py > ph) py -= ph; }
    const ix = (px - (pw / 2 - S.view.cx * V.contentW * z)) / z;
    const iy = (py - (ph / 2 - S.view.cy * V.contentH * z)) / z;
    S.view.zoom = nz;
    S.view.cx = (pw / 2 - (px - ix * nz)) / (V.contentW * nz);
    S.view.cy = (ph / 2 - (py - iy * nz)) / (V.contentH * nz);
    layoutViewer();
  }

  function setZoom(mode) {
    if (mode === 'fit') { S.view.zoom = null; S.view.cx = 0.5; S.view.cy = 0.5; }
    else { S.view.zoom = 1 / devicePixelRatio; }
    layoutViewer();
  }

  function setMode(mode) {
    if (!hasOutput() && mode !== 'source') return;
    S.view.mode = mode;
    store.set('viewMode', mode);
    applyMode();
  }

  function renderEmpty() {
    const node = $('#viewerEmpty');
    node.innerHTML = '';
    if (S.engine && !S.engine.ok) {
      node.append(h('div', { class: 'empty-card' },
        h('h1', { class: 'empty-title', html: 'Connect <em>Visual Enhancer</em>' }),
        h('p', {}, 'Visien renders with Visual Enhancer, the free DLSS 5 neural rendering app by Merserk. It is not included with Visien: download it once and Visien finds it.'),
        h('ol', { class: 'steps' },
          h('li', {}, h('span', { class: 'n' }, '1'), h('span', { html: 'Download the latest release package (<b>the large .zip under Assets</b>, not “Source code”).' })),
          h('li', {}, h('span', { class: 'n' }, '2'), h('span', { html: 'Extract it to your <b>Downloads</b>, Desktop or Documents, or into Visien’s <b>engine</b> folder.' })),
          h('li', {}, h('span', { class: 'n' }, '3'), h('span', { html: 'Press <b>Find automatically</b>.' }))),
        S.engine.reason ? h('div', { class: 'empty-reason' }, S.engine.reason) : null,
        h('div', { class: 'row' },
          h('button', { class: 'btn btn-primary', onclick: () => api('/engine/open-release', {}).catch(fail) }, 'Open download page'),
          h('button', { class: 'btn', onclick: findEngine }, 'Find automatically'),
          h('button', { class: 'btn btn-quiet', onclick: chooseEngineFolder }, 'Choose folder…'),
          h('button', { class: 'btn btn-quiet', onclick: () => api('/reveal', { path: '@engine' }).catch(fail) }, 'Open engine folder'))));
      return;
    }
    if (!S.media.length) {
      node.append(h('div', { class: 'empty-card' },
        h('h1', { class: 'empty-title', html: 'Drop footage <em>here</em>' }),
        h('p', {}, 'Videos and stills from Seedance, Kling, Veo, Midjourney or a camera. Try settings on a few seconds, compare, then send everything to the queue.'),
        h('div', { class: 'row' },
          h('button', { class: 'btn btn-primary', html: icon('plus') + 'Add media', onclick: async () => addPaths(await pickMedia()) }),
          h('button', { class: 'btn btn-quiet', html: icon('folder') + 'Add a folder', onclick: async () => { const f = await pickFolder(); if (f) addPaths([f]); } }))));
    }
  }

  function renderViewerStatus() {
    const node = $('#viewerStatus');
    const m = activeMedia();
    if (!m) { node.textContent = ''; return; }
    if (hasOutput()) {
      const p = S.preview;
      const stale = settingsHash(p.kind) !== S.previewHash;
      const range = p.kind === 'video' ? ` ${fmtTime(p.start)}–${fmtTime(p.start + p.length)}` : '';
      node.innerHTML = `<b>Preview</b>${range} · ${p.seconds ?? '?'} s${stale ? ' · <span style="color:var(--warn)">settings changed since this preview</span>' : ''}`;
    } else if (S.preview && m.kind === 'video') {
      node.innerHTML = `Source at ${fmtTime(S.time)} · <a class="link-btn" id="backToPreview" href="#">show preview</a>`;
      const link = $('#backToPreview');
      if (link) link.addEventListener('click', (e) => { e.preventDefault(); S.previewOn = true; S.time = S.preview.start; buildViewer(); renderTimeline(); });
    } else {
      node.innerHTML = m.kind === 'video' ? `<b>Source</b> · press Preview to render ${S.previewLength} s from the playhead` : '<b>Source</b> · press Preview to render this image';
    }
  }

  // ---------------------------------------------------------------- playback

  function seekPreview(offset) {
    if (!V.b || !S.preview || S.preview.kind !== 'video') return;
    const t = clamp(offset, 0, Math.max(0, S.preview.length - 0.001));
    V.b.currentTime = t;
    if (V.a) V.a.currentTime = t;
    if (S.view.lossless && !S.playing) showStills();
  }

  function syncLoop() {
    if (!S.playing || !V.a || !V.b) return;
    if (Math.abs(V.a.currentTime - V.b.currentTime) > 0.045) V.a.currentTime = V.b.currentTime;
    V.raf = requestAnimationFrame(syncLoop);
  }

  function play() {
    const m = activeMedia();
    if (!m || m.kind !== 'video') return;
    if (!S.preview) { toast('Run a preview first (P).', 'info', 2500); return; }
    if (!S.previewOn) { S.previewOn = true; S.time = S.preview.start; buildViewer(); }
    if (!V.b) return;
    hideStills();
    S.playing = true;
    V.b.play().catch(() => {});
    if (V.a) { V.a.currentTime = V.b.currentTime; V.a.play().catch(() => {}); }
    $('#playButton').innerHTML = icon('pause');
    cancelAnimationFrame(V.raf);
    V.raf = requestAnimationFrame(syncLoop);
  }

  function stopPlayback() {
    S.playing = false;
    cancelAnimationFrame(V.raf);
    if (V.b && V.b.pause) V.b.pause();
    if (V.a && V.a.pause) { V.a.pause(); if (V.b && V.b.currentTime !== undefined) V.a.currentTime = V.b.currentTime; }
    $('#playButton').innerHTML = icon('play');
    if (S.view.lossless) showStills();
  }

  function togglePlay() { if (S.playing) stopPlayback(); else play(); }

  function step(frames) {
    const m = activeMedia();
    if (!m || m.kind !== 'video') return;
    stopPlayback();
    if (hasOutput() && S.preview.kind === 'video') {
      const fps = S.preview.output.fps || m.fps_value || 24;
      const t = clamp(V.b.currentTime + frames / fps, 0, S.preview.length - 0.001);
      seekPreview(t);
      S.time = S.preview.start + t;
    } else {
      S.time = clamp(S.time + frames / (m.fps_value || 24), 0, Math.max(0, m.duration - 0.01));
      loadSourceFrame(true);
    }
    renderTimeline();
  }

  function showStills() {
    if (!S.view.lossless || !hasOutput() || S.preview.kind !== 'video' || !V.b) return;
    const t = V.b.currentTime || 0;
    const key = S.preview.key;
    const load = (img, which) => {
      if (!img) return;
      const src = `/api/preview-still/${key}/${which}?t=${t.toFixed(4)}`;
      const probe = new Image();
      probe.onload = () => { img.src = src; img.hidden = false; };
      probe.src = src;
    };
    load(V.stillA, 'source'); load(V.stillB, 'output');
  }
  function hideStills() { if (V.stillA) V.stillA.hidden = true; if (V.stillB) V.stillB.hidden = true; }

  // ---------------------------------------------------------------- timeline

  function renderTimeline() {
    const m = activeMedia();
    const transport = $('#transport');
    const isVideo = m && m.kind === 'video' && m.duration > 0;
    transport.classList.toggle('disabled', !isVideo);
    const tl = $('#timeline');
    const width = tl.clientWidth || 1;
    if (!isVideo) {
      $('#tlHead').style.left = '0px'; $('#tlWindow').style.display = 'none'; $('#tlReady').classList.remove('on');
      $('#timecode').innerHTML = m && m.kind === 'image' ? 'Still image' : '—';
      return;
    }
    const d = m.duration;
    const x = (t) => (clamp(t, 0, d) / d) * width;
    $('#tlHead').style.left = `${x(S.time)}px`;
    const win = $('#tlWindow');
    win.style.display = '';
    const start = hasOutput() ? S.preview.start : S.time;
    const len = hasOutput() ? S.preview.length : Math.min(S.previewLength, d);
    const winStart = Math.min(start, Math.max(0, d - len));
    win.style.left = `${x(winStart)}px`; win.style.width = `${Math.max(4, x(winStart + len) - x(winStart))}px`;
    const ready = $('#tlReady');
    if (S.preview && S.preview.kind === 'video') {
      ready.classList.add('on');
      ready.style.left = `${x(S.preview.start)}px`; ready.style.width = `${Math.max(3, x(S.preview.start + S.preview.length) - x(S.preview.start))}px`;
    } else ready.classList.remove('on');
    const frame = Math.round(S.time * (m.fps_value || 24));
    $('#timecode').innerHTML = `<b>${fmtTime(S.time)}</b> / ${fmtTime(d)} · f ${frame}`;
  }

  function timelineSeek(clientX) {
    const m = activeMedia();
    if (!m || m.kind !== 'video') return;
    const rect = $('#timeline').getBoundingClientRect();
    const t = clamp((clientX - rect.left) / rect.width, 0, 1) * m.duration;
    S.time = t;
    if (S.preview && S.preview.kind === 'video' && t >= S.preview.start && t <= S.preview.start + S.preview.length) {
      if (!S.previewOn) { S.previewOn = true; buildViewer(); }
      stopPlayback();
      seekPreview(t - S.preview.start);
    } else {
      if (S.previewOn) { stopPlayback(); S.previewOn = false; buildViewer(); }
      loadSourceFrame(false);
    }
    renderTimeline();
    renderViewerStatus();
  }

  // ---------------------------------------------------------------- preview

  async function runPreview(force = false) {
    const m = activeMedia();
    if (!m) { toast('Add a file first.', 'info', 2500); return; }
    if (m.kind !== S.kind) setKind(m.kind);
    if (engineMissing([S.kind])) { toast(engineProblem(), 'err', 9000); return; }
    if (S.checks.problems.length) { toast(S.checks.problems[0], 'err'); return; }
    stopPlayback();
    let start = S.time;
    if (hasOutput() && S.preview.kind === 'video') start = S.preview.start;
    try {
      const job = await api('/preview', { media_id: m.id, settings: S.settings, start, length: S.previewLength, force });
      S.previewJob = job;
      S.previewHash = settingsHash(m.kind);
      watchPreview(job.id, m.id, S.previewHash);
    } catch (error) { fail(error); }
  }

  async function watchPreview(jobId, mediaId, hash) {
    const box = $('#previewProgress');
    box.hidden = false;
    $('#previewButton').disabled = true;
    for (;;) {
      let job;
      try { job = await api('/preview/' + jobId); } catch (error) { box.hidden = true; $('#previewButton').disabled = false; fail(error); return; }
      if (!S.previewJob || S.previewJob.id !== jobId) { return; }
      $('#previewMessage').textContent = job.message || 'Rendering';
      $('#previewPercent').textContent = job.state === 'rendering' ? `${Math.round(job.progress * 100)}%` : '';
      $('#previewBar').style.width = `${Math.round(job.progress * 100)}%`;
      if (job.state === 'done') {
        box.hidden = true; $('#previewButton').disabled = false;
        if (S.activeId !== mediaId) return;
        S.preview = Object.assign({ key: job.key }, job.result);
        S.previewHash = hash;
        S.previewOn = true;
        S.time = S.preview.start || 0;
        if (S.view.mode === 'source') S.view.mode = 'split';
        buildViewer(); renderTimeline();
        return;
      }
      if (job.state === 'failed' || job.state === 'cancelled') {
        box.hidden = true; $('#previewButton').disabled = false;
        if (job.state === 'failed') toast('Preview failed:\n' + job.error, 'err');
        return;
      }
      await new Promise((r) => setTimeout(r, 400));
    }
  }

  // ---------------------------------------------------------------- render queue

  function renderTargets() {
    const ids = S.picked.size ? S.media.filter((m) => S.picked.has(m.id) && !m.missing).map((m) => m.id) : (activeMedia() ? [S.activeId] : []);
    return ids;
  }

  // Visual Enhancer is needed only when a Visual Enhancer card is on (AI-only chains run without it).
  const needsEngine = (kinds) => [...kinds].some((k) => (S.settings[`${k}_enabled_stages`] || []).length > 0);
  const noRtx = () => Boolean(S.engine && S.engine.ok && S.engine.rtx === false);
  const usesAi = (kinds) => [...kinds].some((k) => (S.settings[`vz_${k}_ai`] || []).length > 0);
  // Without an NVIDIA RTX GPU the Visual Enhancer cards are skipped; something must still run.
  const engineMissing = (kinds) => needsEngine(kinds) && (!S.engine || !S.engine.ok || (noRtx() && !usesAi(kinds)));
  const engineProblem = () => (noRtx() ? S.engine.rtx_problem : 'Connect Visual Enhancer first (Settings), or use only AI cards.');

  function updateRenderButton() {
    const ids = renderTargets();
    const kinds = new Set(ids.map((id) => (S.media.find((m) => m.id === id) || {}).kind));
    let label = 'Render';
    if (ids.length === 1) label = kinds.has('image') ? 'Render image' : 'Render video';
    else if (ids.length > 1) label = `Render ${ids.length} ${kinds.size === 1 ? (kinds.has('image') ? 'images' : 'videos') : 'files'}`;
    $('#renderLabel').textContent = label;
    const button = $('#renderButton');
    button.disabled = !ids.length || engineMissing(kinds) || (S.checks.problems.length > 0 && kinds.has(S.kind) && kinds.size === 1);
    button.dataset.tip = engineMissing(kinds) ? engineProblem() : S.checks.problems[0] || uiTip('render') || 'Add to the queue and render (Ctrl+Enter)';
    $('#previewButton').disabled = !activeMedia() || engineMissing([S.kind]) || Boolean(S.previewJob && S.previewJob.state === 'rendering' && !$('#previewProgress').hidden);
  }

  async function render() {
    const ids = renderTargets();
    if (!ids.length) return;
    try {
      const result = await api('/queue', { media_ids: ids, settings: S.settings, preset: (S.presetName || 'Custom') + (isModified() ? ' (edited)' : ''), start: true });
      S.queue = result;
      setQueueOpen(true);
      renderQueue();
      toast(`Added ${result.created.length} to the queue.`, 'ok', 2500);
      pollQueue(true);
    } catch (error) { fail(error); }
  }

  function setQueueOpen(open) {
    S.queueOpen = open;
    store.set('queueOpen', open);
    $('#queue').classList.toggle('open', open);
    $('#queueToggle').setAttribute('aria-expanded', open ? 'true' : 'false');
    requestAnimationFrame(() => { layoutViewer(); renderTimeline(); });
  }

  function stateIcon(state) {
    if (state === 'done') return icon('check');
    if (state === 'failed') return icon('alert');
    if (state === 'cancelled') return icon('x');
    return '';
  }

  function renderQueue() {
    const q = S.queue;
    const jobs = q.jobs || [];
    const counts = { pending: 0, rendering: 0, done: 0, failed: 0, cancelled: 0 };
    jobs.forEach((j) => { counts[j.state] = (counts[j.state] || 0) + 1; });
    const parts = [];
    if (counts.rendering) parts.push(`${counts.rendering} rendering`);
    if (counts.pending) parts.push(`${counts.pending} waiting${q.running ? '' : ' (paused)'}`);
    if (counts.done) parts.push(`${counts.done} done`);
    if (counts.failed) parts.push(`${counts.failed} failed`);
    $('#queueSummary').textContent = parts.join(' · ') || 'Empty';
    const active = jobs.find((j) => j.state === 'rendering');
    const activeBox = $('#queueActive');
    activeBox.innerHTML = '';
    const strip = $('#renderStrip');
    if (active) {
      const pct = Math.round(active.progress * 100);
      const eta = active.eta ? ` · ${fmtDuration(active.eta)} left` : '';
      activeBox.append(h('span', { class: 'qa-name' }, active.name), h('div', { class: 'bar coat-bar' }, h('i', { style: `width:${pct}%` })), h('span', { class: 'mono' }, `${pct}%`));
      strip.hidden = false;
      $('#renderText').textContent = `${active.name} · ${active.message}`;
      $('#renderPercent').textContent = `${pct}%${eta}`;
      $('#renderBar').style.width = `${pct}%`;
    } else strip.hidden = true;
    $('#queueStart').textContent = q.running ? 'Pause' : 'Start';
    $('#queueStart').disabled = !counts.pending && !q.running;
    $('#queueStop').disabled = !counts.rendering;
    $('#queueClear').disabled = !(counts.done + counts.failed + counts.cancelled);

    const list = $('#queueList');
    list.innerHTML = '';
    if (!jobs.length) list.append(h('li', { class: 'queue-empty' }, 'Nothing queued. Press Render to add the selected files.'));
    jobs.forEach((j, index) => {
      const pct = Math.round(j.progress * 100);
      const target = (j.output || j.target || '').split(/[\\/]/).pop();
      const timeText = j.state === 'rendering' ? `${fmtDuration(j.elapsed)}${j.eta ? ' · ' + fmtDuration(j.eta) + ' left' : ''}` : j.state === 'done' ? `in ${fmtDuration(j.elapsed)}` : '';
      const actions = h('div', { class: 'q-actions' });
      const act = (name, title, run, disabled = false) => actions.append(h('button', { class: 'icon-btn', title, html: icon(name), disabled, onclick: run }));
      const call = (action) => () => api('/queue/' + action, { id: j.id }).then((r) => { S.queue = r; renderQueue(); }).catch(fail);
      if (j.state === 'pending') { act('up', 'Move up', call('up'), index === 0); act('down', 'Move down', call('down'), index === jobs.length - 1); act('x', 'Cancel', call('cancel')); }
      if (j.state === 'rendering') act('stop', 'Stop this render', call('cancel'));
      if (j.state === 'done') act('reveal', 'Show in folder', () => api('/reveal', { path: j.output }).catch(fail));
      if (['done', 'failed', 'cancelled'].includes(j.state)) act('retry', 'Render again', call('retry'));
      if (j.state !== 'rendering') act('trash', 'Remove from queue', call('remove'));
      const progress = h('div', { class: 'q-progress' });
      if (j.state === 'failed') progress.append(h('div', { class: 'q-error' }, j.error || 'Failed'));
      else if (j.state === 'rendering' || j.state === 'pending') {
        progress.append(h('div', { class: 'rs-text' }, h('span', {}, j.state === 'pending' ? (q.running ? 'Waiting' : 'Paused') : j.message), h('span', { class: 'mono' }, j.state === 'rendering' ? `${pct}%` : '')));
        progress.append(h('div', { class: 'bar' }, h('i', { style: `width:${j.state === 'rendering' ? pct : 0}%` })));
      } else progress.append(h('div', { class: 'rs-text' }, h('span', {}, j.state === 'done' ? 'Done' : 'Cancelled'), h('span', { class: 'mono' }, '')));
      list.append(h('li', { class: `q-item ${j.state}` },
        h('span', { class: 'q-state', html: stateIcon(j.state) }),
        h('div', { class: 'q-main' }, h('div', { class: 'q-name', title: j.source }, j.name),
          h('div', { class: 'q-sub' }, `${j.preset || 'Custom'}${target ? ' → ' + target : ''}`, timeText ? h('span', { class: 'mono' }, ` · ${timeText}`) : null)),
        progress, actions));
    });
    const log = $('#queueLogView');
    log.hidden = !S.showLog;
    list.hidden = S.showLog;
    if (S.showLog) { log.textContent = (q.log || []).join('\n') || 'No log entries yet.'; log.scrollTop = log.scrollHeight; }
  }

  let queueTimer = null;
  async function pollQueue(soon = false) {
    clearTimeout(queueTimer);
    if (!soon) {
      try { S.queue = await api('/queue'); renderQueue(); } catch { /* server busy */ }
    }
    const busy = (S.queue.jobs || []).some((j) => j.state === 'rendering' || (j.state === 'pending' && S.queue.running));
    queueTimer = setTimeout(() => pollQueue(false), soon ? 300 : busy ? 800 : S.queueOpen ? 2500 : 4000);
  }

  // ---------------------------------------------------------------- engine & settings

  function renderEngine() {
    const e = S.engine;
    const led = $('#engineLed'), text = $('#engineText');
    if (!e) { led.className = 'led'; text.textContent = 'Checking engine…'; return; }
    if (e.ok && e.rtx === false) {
      led.className = 'led warn';
      text.textContent = `Visual Enhancer ${e.version || ''} · no NVIDIA GPU · AI cards only`;
      text.parentElement && (text.parentElement.dataset.tip = e.rtx_problem || '');
    } else if (e.ok) {
      const gpu = S.devices.find((d) => String(d.index) === String(S.config.gpu)) || S.devices[0];
      led.className = 'led ok';
      text.textContent = `Visual Enhancer ${e.version || ''}${gpu ? ' · ' + gpu.name.replace(/^NVIDIA (GeForce )?/, '') : ''}`;
    } else { led.className = 'led err'; text.textContent = 'Visual Enhancer not connected'; }
  }

  async function refreshEngine() {
    try {
      const state = await api('/state');
      S.engine = state.engine; S.config = state.settings; S.releaseUrl = state.release_url; S.version = state.version;
      if (S.engine.ok) {
        try { const d = await api('/engine/devices'); S.devices = d.devices || []; } catch { S.devices = []; }
        if (S.engine.rtx == null) { try { S.engine = (await api('/state')).engine; } catch { /* keep */ } }
      }
    } catch (error) { S.engine = { ok: false, reason: error.message }; }
    renderEngine(); renderEmpty(); updateRenderButton();
  }

  async function findEngine() {
    try {
      const result = await api('/engine/scan', {});
      S.engine = result.status;
      await refreshEngine();
      if (S.engine.ok) toast(`Found Visual Enhancer ${S.engine.version || ''} in ${S.engine.path}`, 'ok');
      else toast(result.found.length ? S.engine.reason : 'Visual Enhancer was not found in Downloads, Desktop, Documents or Visien\\engine.', 'err');
      buildViewer();
      return result;
    } catch (error) { fail(error); return null; }
  }

  async function chooseEngineFolder() {
    const folder = await pickFolder();
    if (!folder) return;
    try { S.engine = await api('/engine/select', { path: folder }); await refreshEngine(); toast(`Using Visual Enhancer ${S.engine.version || ''}.`, 'ok'); buildViewer(); } catch (error) { fail(error); }
  }

  function updateSection() {
    const line = h('span', { class: 'field-hint' }, `Installed: Visien ${S.version || ''}`);
    const open = h('button', { class: 'btn btn-sm', hidden: true, 'data-tip': 'Opens the release page with the download and what changed.' }, 'Download');
    let url = '';
    open.addEventListener('click', () => api('/update/open', { url }).catch(fail));
    const check = h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Looks for a newer Visien on GitHub.', onclick: async () => {
      line.textContent = 'Checking…';
      try {
        const r = await api('/update');
        url = r.url || '';
        if (!r.ok) { line.textContent = `Could not check for updates (${r.error || 'offline'}).`; open.hidden = !url; open.textContent = 'Release page'; return; }
        line.textContent = r.newer ? `Visien ${r.latest} is available (installed: ${r.current}).` : `Visien ${r.current} is the newest version.`;
        open.hidden = !r.newer; open.textContent = 'Download';
      } catch (error) { line.textContent = error.message; }
    } }, 'Check for updates');
    return h('section', {}, h('h4', {}, 'Updates'), h('div', { class: 'inline-row' }, line, h('span', { class: 'grow' }), check, open),
      h('p', { class: 'field-hint' }, 'New versions are published on GitHub. Extract the new zip over your Visien folder; settings, presets and models stay.'));
  }

  async function openSettings() {
    await refreshEngine();
    const e = S.engine || {};
    const statusLine = h('div', { class: 'inline-row' }, h('span', { class: `led ${e.ok ? 'ok' : 'err'}` }), h('b', {}, e.ok ? `Connected · Visual Enhancer ${e.version || ''}` : 'Not connected'));
    const found = h('div', { class: 'found-list' });
    const engineInfo = h('dl', { class: 'kv' }, h('dt', {}, 'Folder'), h('dd', {}, e.path || '—'), ...(e.ok ? [] : [h('dt', {}, 'Problem'), h('dd', { style: 'color:var(--warn)' }, e.reason || '')]),
      ...(e.ok && e.rtx === false ? [h('dt', {}, 'GPU'), h('dd', { style: 'color:var(--warn)' }, e.rtx_problem || '')] : []));
    const gpuSelect = h('select', { 'data-tip': 'Graphics card Visual Enhancer renders on. Automatic is right for one card.' }, h('option', { value: 'auto' }, 'Automatic (Visual Enhancer chooses)'),
      S.devices.map((d) => h('option', { value: String(d.index), selected: String(S.config.gpu) === String(d.index) }, `${d.index} · ${d.name}${d.memory_mb ? ' · ' + Math.round(d.memory_mb / 1024) + ' GB' : ''}${d.ai_compatible === false ? ' (no AI support)' : ''}`)));
    const outInput = h('input', { class: 'input', 'data-tip': 'Folder for rendered files. Empty uses Videos\\Visien.', value: S.config.output_dir || '', placeholder: S.config.output_dir_effective || '', spellcheck: 'false' });
    const suffix = h('input', { class: 'input', 'data-tip': 'Text added to the end of every output file name.', value: S.config.suffix || '_Visien', style: 'max-width:160px', spellcheck: 'false' });
    const naming = S.config.naming || 'suffix';
    const radioSuffix = h('input', { type: 'radio', 'data-tip': 'Output is named like the source plus the suffix.', name: 'naming', value: 'suffix', checked: naming === 'suffix' });
    const radioCopy = h('input', { type: 'radio', 'data-tip': 'Output keeps exactly the source name (in the output folder).', name: 'naming', value: 'copy', checked: naming === 'copy' });
    const keep = h('input', { class: 'input mono', 'data-tip': 'How many previews are kept so going back to one is instant.', type: 'number', min: 3, max: 200, value: S.config.keep_previews || 12, style: 'max-width:100px' });
    const cacheGb = h('input', { class: 'input mono', 'data-tip': 'Disk space previews may use. Older previews are deleted first.', type: 'number', min: 1, max: 500, value: S.config.preview_cache_gb || 10, style: 'max-width:100px' });
    const usage = h('span', { class: 'field-hint' }, '');
    api('/previews').then((u) => { usage.textContent = `Now: ${u.count} preview${u.count === 1 ? '' : 's'}, ${fmtBytes(u.bytes) || '0 B'}`; }).catch(() => {});
    const body = h('div', { style: 'display:flex;flex-direction:column;gap:22px' },
      h('section', {}, h('h4', {}, 'Visual Enhancer engine'), statusLine, engineInfo,
        h('div', { class: 'inline-row' },
          h('button', { class: 'btn btn-sm', 'data-tip': 'Searches Downloads, Desktop, Documents and the engine folder for Visual Enhancer and connects the newest version.', onclick: async () => { const r = await findEngine(); if (r) { found.innerHTML = ''; r.found.forEach((f) => found.append(h('div', { class: `found-item ${f.complete ? '' : 'bad'}` }, h('span', { class: 'grow' }, f.path), h('span', {}, f.complete ? 'complete' : 'missing ' + f.missing.join(', '))))); } } }, 'Find automatically'),
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Pick the folder that contains VE_CLI.exe yourself.', onclick: chooseEngineFolder }, 'Choose folder…'),
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Starts Visual Enhancer once and lists the graphics cards it can use.', onclick: async () => { try { const r = await api('/engine/test', {}); toast(`Visual Enhancer works. GPUs: ${(r.devices || []).map((d) => d.name).join(', ') || 'none listed'}`, 'ok'); } catch (error) { fail(error); } } }, 'Test'),
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Opens the official Visual Enhancer release page in your browser.', onclick: () => api('/engine/open-release', {}).catch(fail) }, 'Download page'),
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Opens the connected Visual Enhancer folder in Explorer.', onclick: () => api('/reveal', { path: '@engine' }).catch(fail) }, 'Engine folder')),
        found),
      h('section', {}, h('h4', {}, 'GPU'), gpuSelect, h('p', { class: 'field-hint' }, 'Passed to Visual Enhancer as --gpu. Automatic is right for one graphics card.')),
      h('section', {}, h('h4', {}, 'Output'),
        h('label', { class: 'lbl' }, 'Folder', h('div', { class: 'inline-row' }, outInput,
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Choose the output folder.', onclick: async () => { const f = await pickFolder(outInput.value || S.config.output_dir_effective); if (f) outInput.value = f; } }, 'Browse'),
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Opens the output folder in Explorer.', onclick: () => api('/reveal', { path: '@output' }).catch(fail) }, 'Open'))),
        h('div', { class: 'radio-row' }, h('label', {}, radioSuffix, 'Add a suffix:'), suffix, h('label', {}, radioCopy, 'Keep the source name')),
        h('p', { class: 'field-hint' }, 'Existing files are never overwritten; Visien adds _2, _3 … instead.')),
      h('section', {}, h('h4', {}, 'Preview cache'),
        h('p', { class: 'field-hint' }, 'Previews are kept lossless (FFV1) so the Lossless view shows exact pixels. 3 s of 4K output takes about 1 GB.'),
        h('div', { class: 'inline-row' }, h('label', { class: 'lbl' }, 'Keep up to', keep), h('label', { class: 'lbl' }, 'and at most (GB)', cacheGb)),
        h('div', { class: 'inline-row' }, usage, h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Deletes every stored preview. Source files and renders are not touched.', onclick: async () => {
          try { await api('/previews/clear', {}); usage.textContent = 'Now: 0 previews'; S.preview = null; S.previewOn = false; buildViewer(); renderTimeline(); } catch (error) { fail(error); }
        } }, 'Clear preview cache'))),
      modelsSection(),
      shareSection(),
      updateSection(),
      h('section', {}, h('h4', {}, 'About'), h('div', { class: 'about', html:
        `<b>Visien ${S.version || ''}</b> — enhancement studio for AI video and images.<br>` +
        `Rendering by <b>Visual Enhancer</b> by Merserk (DLSS 5 neural rendering), installed separately under its own licence; Visien does not include or modify it. ` +
        `AI stages: SeedVR2 by ByteDance (Apache 2.0), Practical-RIFE (MIT), GFPGAN (Apache 2.0), CodeFormer by NTU S-Lab (non-commercial licence), YuNet (MIT), PyTorch (BSD). ` +
        `NVIDIA, DLSS and RTX are trademarks of NVIDIA Corporation. ffmpeg (GPL) is used for previews and exports.` })));
    const settingsModal = modal({
      title: 'Settings', body,
      actions: [{ label: 'Close' }, { label: 'Save', primary: true, run: async () => {
        try {
          S.config = await api('/settings', { gpu: gpuSelect.value, output_dir: outInput.value.trim(), suffix: suffix.value.trim() || '_Visien',
            naming: radioCopy.checked ? 'copy' : 'suffix', keep_previews: Number(keep.value) || 12, preview_cache_gb: Number(cacheGb.value) || 10 });
          renderEngine(); toast('Settings saved.', 'ok', 2000);
        } catch (error) { fail(error); return true; }
        return false;
      } }],
    });
    const stop = new MutationObserver(() => { if (!settingsModal.box.isConnected) { stop.disconnect(); modelListeners.clear(); } });
    stop.observe($('#modalRoot'), { childList: true });
  }

  function modelsSection() {
    const list = h('div', { class: 'model-list' });
    const runtimeLine = h('div', { class: 'field-hint' });
    const RECOMMENDED = ['runtime', 'seedvr2_vae', 'seedvr2_3b_fp8', 'rife426', 'yunet', 'gfpgan'];
    const draw = () => {
      list.innerHTML = '';
      if (!S.models) { list.append(h('p', {}, 'Model information is not available.')); return; }
      const info = S.models.runtime;
      const api_ = info && info.backend === 'rocm' ? 'ROCm' : 'CUDA';
      runtimeLine.textContent = info ? (info.ok ? `AI runtime: PyTorch ${info.torch}${info.cuda ? ` · ${api_} on ${info.gpu}` : ' · no usable GPU found (AI runs on the CPU, very slowly)'}${info.vram_gb ? ' · ' + info.vram_gb + ' GB' : ''}` : `AI runtime problem: ${info.error || 'does not start'}`) : '';
      let group = '';
      S.models.components.forEach((c) => {
        if (c.group !== group) { group = c.group; list.append(h('div', { class: 'model-group' }, group)); }
        const job = c.job;
        const busy = job && ['queued', 'downloading', 'installing'].includes(job.state);
        const state = c.installed ? h('span', { class: 'model-state ok', html: icon('check') + 'Installed' })
          : busy ? h('span', { class: 'model-state' }, job.state === 'queued' ? 'Waiting' : `${Math.round((job.progress || 0) * 100)}%`)
            : job && job.state === 'error' ? h('span', { class: 'model-state err', 'data-tip': job.error }, 'Failed') : h('span', { class: 'model-state' }, 'Not installed');
        const action = c.installed ? h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Deletes this file from the Visien folder to free disk space.', onclick: async () => {
          if (!(await confirmModal('Remove', `Remove ${c.title} (${fmtBytes(c.size)})? You can install it again later.`, 'Remove', true))) return;
          try { S.models = await api('/models/remove', { id: c.id }); draw(); renderCards({ keepScroll: true }); refreshPlan(); } catch (error) { fail(error); }
        } }, 'Remove') : h('button', { class: 'btn btn-sm', 'data-tip': `Downloads ${c.title} (${fmtBytes(c.size)}) from its official source.`, disabled: busy, onclick: () => installModels(c.id === 'runtime' ? ['runtime'] : ['runtime', c.id]) }, 'Install');
        list.append(h('div', { class: `model-row ${c.installed ? 'installed' : ''}` },
          h('div', { class: 'mr-main' },
            h('div', { class: 'mr-title' }, c.title, c.accept ? h('span', { class: 'badge-nc', 'data-tip': c.license }, 'non-commercial') : null),
            h('div', { class: 'mr-sub' }, [c.detail, c.license, fmtBytes(c.size)].filter(Boolean).join(' · ')),
            busy && job.message ? h('div', { class: 'mr-sub mono' }, job.message) : null,
            busy ? h('div', { class: 'bar' }, h('i', { style: `width:${Math.round((job.progress || 0) * 100)}%` })) : null),
          state, action));
      });
    };
    modelListeners.add(draw);
    const section = h('section', {}, h('h4', {}, 'AI models'),
      h('p', { class: 'field-hint' }, 'SeedVR2, RIFE and Face Restore run in Visien’s own AI runtime on your GPU. Files are downloaded from the official model releases into the Visien folder (ai and models) and checked against their published checksums.'),
      h('div', { class: 'inline-row' },
        h('button', { class: 'btn btn-sm', 'data-tip': `AI runtime, SeedVR2 3B, RIFE 4.26, the face detector and GFPGAN (about ${fmtBytes(sizeOf(RECOMMENDED))}). All of them allow commercial use.`, onclick: () => installModels(RECOMMENDED) }, 'Install recommended'),
        h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Starts the AI runtime and reports the GPU it found.', onclick: async () => {
          runtimeLine.textContent = 'Testing the AI runtime…';
          try { const info = await api('/models/check', {}); if (S.models) S.models.runtime = info; draw(); } catch (error) { runtimeLine.textContent = error.message; }
        } }, 'Test runtime')),
      runtimeLine, list);
    loadModels().then(draw);
    draw();
    return section;
  }

  // ---------------------------------------------------------------- share (packages)

  function shareSection() {
    const line = h('div', { class: 'field-hint mono' });
    const bar = h('div', { class: 'bar', hidden: true }, h('i', { style: 'width:0%' }));
    const actions = h('div', { class: 'inline-row' });
    let timer = 0;
    const draw = (job) => {
      actions.innerHTML = '';
      const running = job && job.state === 'running';
      bar.hidden = !running;
      if (running) bar.firstChild.style.width = `${Math.round((job.progress || 0) * 100)}%`;
      line.textContent = !job || job.state === 'idle' ? '' : job.state === 'error' ? `Failed: ${job.error}` : `${job.message || ''}${job.state === 'done' ? ' · ' + fmtBytes(job.size) : ''}`;
      if (running) {
        actions.append(h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Stops creating the package and deletes the unfinished file.', onclick: async () => { draw(await api('/package/cancel', {})); } }, 'Cancel'));
      } else {
        actions.append(
          h('button', { class: 'btn btn-sm', 'data-tip': 'One zip with everything: the app, its own Python, ffmpeg, the AI runtime and the recommended models (about 9 GB). The other PC needs no internet; only Visual Enhancer is downloaded separately.', onclick: () => make('full') }, 'Create full package'),
          h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'The app only (a few MB). install.bat downloads Python and ffmpeg; the AI models are installed from Settings.', onclick: () => make('slim') }, 'Create small package'));
        if (job && job.state === 'done') actions.append(h('button', { class: 'btn btn-sm btn-quiet', 'data-tip': 'Shows the package in Explorer.', onclick: () => api('/reveal', { path: job.path }).catch(fail) }, 'Show'));
      }
    };
    const poll = async () => {
      clearTimeout(timer);
      if (!line.isConnected && timer) return;
      try { const job = await api('/package'); draw(job); if (job.state === 'running') timer = setTimeout(poll, 1000); } catch { /* closed */ }
    };
    const make = async (kind) => {
      const folder = await pickFolder(S.config.last_dir || '');
      if (!folder) return;
      try { draw(await api('/package', { kind, folder })); timer = setTimeout(poll, 800); } catch (error) { fail(error); }
    };
    poll();
    return h('section', {}, h('h4', {}, 'Share Visien'),
      h('p', { class: 'field-hint' }, 'Creates a zip you can give to another PC. Visual Enhancer and CodeFormer are never included (their licences do not allow it). Pick a folder outside the Visien folder.'),
      actions, bar, line);
  }

  // ---------------------------------------------------------------- render all

  function renderAll() {
    $$('#kindSwitch button').forEach((b) => b.classList.toggle('on', b.dataset.kind === S.kind));
    renderPresetButton();
    renderCards();
    renderMedia();
    buildViewer();
    renderTimeline();
    changed();
  }

  // ---------------------------------------------------------------- events

  function bindEvents() {
    $$('#kindSwitch button').forEach((b) => b.addEventListener('click', () => setKind(b.dataset.kind)));
    $$('#modeSwitch button').forEach((b) => b.addEventListener('click', () => setPipelineMode(b.dataset.mode)));
    $('#presetButton').addEventListener('click', (e) => { e.stopPropagation(); openPresetMenu(); });
    document.addEventListener('mousedown', (e) => { const menu = $('#presetMenu'); if (!menu.hidden && !menu.contains(e.target) && !$('#presetButton').contains(e.target)) menu.hidden = true; });
    $('#enginePill').addEventListener('click', openSettings);
    $('#settingsButton').addEventListener('click', openSettings);
    $('#addMedia').addEventListener('click', async () => addPaths(await pickMedia()));
    $('#addMediaEmpty').addEventListener('click', async () => addPaths(await pickMedia()));
    $('#addFolder').addEventListener('click', async () => { const f = await pickFolder(S.config.last_dir || ''); if (f) addPaths([f]); });
    $('#removeMedia').addEventListener('click', removeMedia);
    $('#selectAll').addEventListener('change', (e) => { S.picked = new Set(e.target.checked ? S.media.map((m) => m.id) : []); renderMedia(); });
    $('#collapseAll').addEventListener('click', () => {
      const ids = S.settings[orderKey()];
      const on = onSet();
      const allCollapsed = ids.every((id) => S.collapsed[id] ?? !on.has(id));
      ids.forEach((id) => { S.collapsed[id] = !allCollapsed; });
      $('#collapseAll').textContent = allCollapsed ? 'Collapse all' : 'Expand all';
      renderCards({ keepScroll: true }); store.set('collapsed', S.collapsed);
    });

    $$('#viewModes button').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
    $('#zoomFit').addEventListener('click', () => setZoom('fit'));
    $('#zoom100').addEventListener('click', () => setZoom('100'));
    $('#losslessToggle').addEventListener('click', () => { S.view.lossless = !S.view.lossless; applyMode(); if (S.view.lossless && !S.playing) showStills(); else hideStills(); });

    const viewer = $('#viewer');
    viewer.addEventListener('wheel', (e) => { if (!activeMedia()) return; e.preventDefault(); zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY); }, { passive: false });
    let drag = null;
    viewer.addEventListener('mousedown', (e) => {
      if (e.button !== 0 || e.target.closest('.viewer-progress, .viewer-empty')) return;
      const onDivider = e.target.closest('#divider') || (e.shiftKey && S.view.mode === 'split');
      drag = { x: e.clientX, y: e.clientY, cx: S.view.cx, cy: S.view.cy, divider: Boolean(onDivider) };
      if (!onDivider) { viewer.classList.add('dragging'); if (!S.view.zoom) S.view.zoom = fitZoom(); }
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      if (!(e.buttons & 1)) { drag = null; viewer.classList.remove('dragging'); return; }
      if (drag.divider) {
        const rect = viewer.getBoundingClientRect();
        S.view.split = clamp((e.clientX - rect.left) / rect.width, 0.02, 0.98);
      } else {
        const z = S.view.zoom || fitZoom();
        S.view.cx = drag.cx - (e.clientX - drag.x) / (V.contentW * z);
        S.view.cy = drag.cy - (e.clientY - drag.y) / (V.contentH * z);
      }
      layoutViewer();
    });
    window.addEventListener('mouseup', () => { drag = null; viewer.classList.remove('dragging'); });
    viewer.addEventListener('dblclick', (e) => { if (e.target.closest('#divider, .viewer-empty')) return; if (S.view.zoom && Math.abs(S.view.zoom * devicePixelRatio - 1) < 0.01) setZoom('fit'); else { setZoom('100'); zoomAt(1, e.clientX, e.clientY); } });
    new ResizeObserver(() => { layoutViewer(); renderTimeline(); }).observe(viewer);

    $('#playButton').addEventListener('click', togglePlay);
    $('#stepBack').addEventListener('click', () => step(-1));
    $('#stepFwd').addEventListener('click', () => step(1));
    let scrubbing = false;
    $('#timeline').addEventListener('mousedown', (e) => { scrubbing = true; timelineSeek(e.clientX); });
    window.addEventListener('mousemove', (e) => { if (scrubbing) { if (e.buttons & 1) timelineSeek(e.clientX); else scrubbing = false; } });
    window.addEventListener('mouseup', () => { scrubbing = false; });

    $('#previewButton').addEventListener('click', () => runPreview(false));
    $('#previewAgain').addEventListener('click', () => runPreview(true));
    $('#previewCancel').addEventListener('click', () => { api('/preview/cancel', {}).catch(fail); });
    const lengthSelect = $('#previewLength');
    lengthSelect.value = String(S.previewLength);
    lengthSelect.addEventListener('change', () => { S.previewLength = Number(lengthSelect.value); store.set('previewLength', S.previewLength); renderTimeline(); renderViewerStatus(); });
    $('#openOutput').addEventListener('click', () => api('/reveal', { path: '@output' }).catch(fail));
    $('#renderButton').addEventListener('click', render);

    $('#queueToggle').addEventListener('click', () => setQueueOpen(!S.queueOpen));
    $('#queueStart').addEventListener('click', () => api('/queue/' + (S.queue.running ? 'pause' : 'start'), {}).then((r) => { S.queue = r; renderQueue(); pollQueue(true); }).catch(fail));
    $('#queueStop').addEventListener('click', () => api('/queue/stop', {}).then((r) => { S.queue = r; renderQueue(); }).catch(fail));
    $('#queueClear').addEventListener('click', () => api('/queue/clear', {}).then((r) => { S.queue = r; renderQueue(); }).catch(fail));
    $('#queueLog').addEventListener('click', () => { S.showLog = !S.showLog; $('#queueLog').classList.toggle('on', S.showLog); if (!S.queueOpen) setQueueOpen(true); renderQueue(); });

    // drag and drop (paths arrive through the native bridge)
    let dragDepth = 0;
    window.addEventListener('dragenter', (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { dragDepth += 1; $('#dropOverlay').hidden = false; } });
    window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('#dropOverlay').hidden = true; });
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', async (e) => {
      e.preventDefault(); dragDepth = 0; $('#dropOverlay').hidden = true;
      if (!(await hasNative())) toast('Drag and drop needs the Visien window. In the browser, use Add media.', 'info');
    });

    document.addEventListener('keydown', (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      if (['input', 'select', 'textarea'].includes(tag) || $('#modalRoot').children.length) return;
      if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); render(); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (e.key === ' ') { e.preventDefault(); togglePlay(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); step(e.shiftKey ? -10 : -1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); step(e.shiftKey ? 10 : 1); }
      else if (k === 'p') runPreview(false);
      else if (k === '1') setMode('split');
      else if (k === '2') setMode('side');
      else if (k === '3') setMode('source');
      else if (k === '4') setMode('output');
      else if (k === '5') setMode('stack');
      else if (k === 'f') setZoom('fit');
      else if (k === 'z') setZoom('100');
      else if (k === 'l') $('#losslessToggle').click();
      else if (k === 'q') setQueueOpen(!S.queueOpen);
      else if (e.key === 'Delete' && document.activeElement && document.activeElement.closest('.media-panel')) removeMedia();
    });
    window.addEventListener('resize', () => { layoutViewer(); renderTimeline(); });
  }

  // UI errors go to the app log (data\\visien.log) so problems on other PCs can be diagnosed
  const report = (text) => { try { navigator.sendBeacon('/api/client-log', new Blob([JSON.stringify({ text: String(text).slice(0, 2000) })], { type: 'application/json' })); } catch { /* ignore */ } };
  window.addEventListener('error', (e) => report(`${e.message} @ ${e.filename}:${e.lineno}`));
  window.addEventListener('unhandledrejection', (e) => report(`unhandled: ${e.reason && (e.reason.stack || e.reason.message) || e.reason}`));

  // called by the native window when files are dropped
  window.visien = { dropped: (paths) => addPaths(paths) };

  // ---------------------------------------------------------------- start

  async function boot() {
    bindEvents();
    bindTips();
    setQueueOpen(S.queueOpen);
    try {
      S.schema = await api('/schema');
      S.schema.stages.forEach((st) => { S.stage[st.id] = st; });
      applyUiTips();
      await Promise.all([loadPresets(), loadModels()]);
      if (S.models && S.models.busy) watchModels();
      const saved = store.get('settings', null);
      if (saved) {
        S.settings = Object.assign(clone(S.schema.defaults), saved);
        // settings saved before Visien had AI stages: keep their Visual Enhancer order
        ['video', 'image'].forEach((kind) => {
          if (!saved[`vz_${kind}_order`] && Array.isArray(saved[`${kind}_stage_order`])) {
            const ve = saved[`${kind}_stage_order`];
            const vz = S.schema.vz_orders[kind];
            const order = [...ve];
            vz.filter((id) => S.schema.ai_ids.includes(id)).forEach((ai) => {
              const i = vz.indexOf(ai);
              const after = vz.slice(0, i).reverse().find((x) => order.includes(x));
              order.splice(after ? order.indexOf(after) + 1 : 0, 0, ai);
            });
            S.settings[`vz_${kind}_order`] = order.concat(vz.filter((x) => !order.includes(x)));
          }
        });
        S.baseline = store.get('baseline', null);
      } else {
        const first = S.presets.find((p) => p.builtin) || null;
        if (first) { S.settings = Object.assign(clone(S.schema.defaults), clone(first.settings)); S.baseline = clone(S.settings); S.presetId = first.id; S.presetName = first.name; }
        else { S.settings = clone(S.schema.defaults); S.presetName = 'Custom'; }
      }
      S.media = await api('/media');
      if (!activeMedia()) S.activeId = S.media.length ? S.media[0].id : null;
      const m = activeMedia();
      if (m) S.kind = m.kind;
      renderAll();
    } catch (error) { fail(error); }
    await refreshEngine();
    buildViewer();
    pollQueue();
    setInterval(refreshEngine, 60000);
  }

  boot();
})();
