/* Audit notebook selection and streaming execution. */
(() => {
  'use strict';
  const storageKey = 'downloader_audit_selection';
  let entries = [];
  let controller = null;
  let loaded = false;
  const el = id => document.getElementById(id);
  const selected = () => Array.from(document.querySelectorAll('.audit-checkbox:checked'), cb => cb.value);
  function savedSelection() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey));
      return Array.isArray(value) ? value : null;
    } catch (_) { return null; }
  }
  function syncSelection() {
    el('btn-run-audits').disabled = Boolean(controller) || selected().length === 0;
    el('btn-run-audits').innerHTML = `<i class="bi bi-play-fill"></i> Executar selecionados (${selected().length})`;
    try { localStorage.setItem(storageKey, JSON.stringify(selected())); } catch (_) {}
  }
  function badge(id, label, style) {
    const node = el(`audit-state-${id}`);
    if (node) {
      node.className = `badge text-bg-${style}`;
      node.textContent = label;
    }
  }
  function render(previous) {
    const container = el('audits-list');
    container.replaceChildren();
    for (const item of entries) {
      const row = document.createElement('div');
      row.className = 'border rounded p-3 mb-2';
      const top = document.createElement('div');
      top.className = 'd-flex align-items-center gap-2';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'form-check-input audit-checkbox m-0';
      checkbox.id = `audit-select-${item.id}`;
      checkbox.value = item.id;
      checkbox.checked = previous === null ? item.ready : previous.includes(item.id);
      checkbox.addEventListener('change', syncSelection);
      const label = document.createElement('label');
      label.className = 'fw-bold flex-grow-1';
      label.htmlFor = checkbox.id;
      label.textContent = item.title;
      const status = document.createElement('span');
      status.id = `audit-state-${item.id}`;
      top.append(checkbox, label, status);
      row.append(top);
      if (item.note) {
        const note = document.createElement('p');
        note.className = 'small text-muted mt-2 mb-1';
        note.textContent = item.note;
        row.append(note);
      }
      for (const problem of item.problems) {
        const warning = document.createElement('p');
        warning.className = 'small text-danger mt-2 mb-1';
        warning.textContent = problem;
        row.append(warning);
      }
      const detail = document.createElement('details');
      detail.className = 'small mt-2';
      const summary = document.createElement('summary');
      summary.textContent = 'Arquivo do audit, entradas e destinos';
      detail.append(summary);
      for (const [heading, paths] of [['Arquivo do audit', [item.path]], ['Entradas', item.inputs], ['Destinos', item.outputs]]) {
        const title = document.createElement('div');
        title.className = 'fw-bold mt-2';
        title.textContent = heading;
        detail.append(title);
        for (const path of paths) {
          const line = document.createElement('div');
          line.className = 'font-monospace text-break';
          line.textContent = path;
          detail.append(line);
        }
      }
      row.append(detail);
      container.append(row);
      badge(item.id, item.ready ? 'Disponível' : 'Entrada pendente', item.ready ? 'success' : 'warning');
    }
    syncSelection();
  }
  async function refresh() {
    if (controller) return;
    el('btn-run-audits').disabled = true;
    el('btn-audits-refresh').disabled = true;
    el('audits-summary').textContent = 'Verificando audits e entradas…';
    const previous = loaded ? selected() : savedSelection();
    try {
      const response = await fetch(`${WORKFLOW_API_BASE}/api/audits`);
      if (!response.ok) throw new Error(`Não foi possível verificar os audits (HTTP ${response.status}).`);
      const result = await response.json();
      entries = result.audits;
      loaded = true;
      render(previous);
      el('audits-summary').textContent = `${entries.filter(item => item.ready).length} de ${entries.length} audits com entradas disponíveis · semana ${result.week}. A verificação não confirma o conteúdo dos dados.`;
    } catch (error) {
      entries = [];
      loaded = false;
      el('audits-list').replaceChildren();
      el('audits-summary').textContent = error.message;
    } finally {
      el('btn-audits-refresh').disabled = false;
      el('btn-run-audits').disabled = !loaded || selected().length === 0;
    }
  }
  function event(line) {
    if (!line.startsWith('AUDIT_EVENT=')) return;
    const item = JSON.parse(line.slice('AUDIT_EVENT='.length));
    const labels = {running: 'Executando', completed: 'Concluído', failed: 'Falhou', blocked: 'Entrada pendente'};
    const styles = {running: 'primary', completed: 'success', failed: 'danger', blocked: 'warning'};
    badge(item.id, labels[item.status] || item.status, styles[item.status] || 'secondary');
    if (item.status === 'running') {
      const title = entries.find(entry => entry.id === item.id)?.title || item.id;
      const entry = entries.find(entry => entry.id === item.id);
      el('audits-status').textContent = entry?.path.endsWith('.py') ? `${title} · executando script` : `${title} · célula ${item.cell}`;
    }
  }
  async function run() {
    if (controller) return;
    const ids = selected();
    if (!ids.length) return;
    controller = new AbortController();
    const log = el('audits-log');
    log.value = '';
    el('audits-status').textContent = 'Verificando seleção…';
    for (const id of ids) badge(id, 'Aguardando', 'secondary');
    document.querySelectorAll('#tab-audits button, .audit-checkbox').forEach(node => { node.disabled = true; });
    el('btn-cancel-audits').disabled = false;
    let pending = '';
    let completed = false;
    try {
      const response = await fetch(`${WORKFLOW_API_BASE}/api/run-audits`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({audit_ids: ids}), signal: controller.signal
      });
      if (!response.ok) throw new Error(await response.text());
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      function append(text) {
        log.value += text;
        log.scrollTop = log.scrollHeight;
        pending += text;
        const lines = pending.split('\n');
        pending = lines.pop();
        for (const line of lines) {
          event(line);
          if (line.trim() === 'AUDITS COMPLETED.') completed = true;
          if (line.trim() === 'AUDITS FAILED.') completed = false;
        }
      }
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        append(decoder.decode(value, {stream: true}));
      }
      append(decoder.decode() + '\n');
      el('audits-status').textContent = completed ? 'Audits concluídos. Relatórios salvos nos destinos indicados.' : 'Execução interrompida por falha. Confira o log; audits anteriores podem ter atualizado seus relatórios.';
    } catch (error) {
      const cancelled = error.name === 'AbortError';
      el('audits-status').textContent = cancelled ? 'Cancelado. Confira o log e os relatórios que já foram gravados.' : `Falha: ${error.message}`;
      if (!cancelled) log.value += `\nErro: ${error.message}\n`;
    } finally {
      if (!completed) {
        for (const id of ids) {
          const state = el(`audit-state-${id}`)?.textContent;
          if (state === 'Executando') badge(id, 'Interrompido', 'warning');
          if (state === 'Aguardando') badge(id, 'Não executado', 'secondary');
        }
      }
      controller = null;
      document.querySelectorAll('#tab-audits button, .audit-checkbox').forEach(node => { node.disabled = false; });
      el('btn-cancel-audits').disabled = true;
      syncSelection();
    }
  }
  document.addEventListener('DOMContentLoaded', () => {
    el('tab-audits-btn').addEventListener('shown.bs.tab', () => { if (!loaded) refresh(); });
    el('btn-audits-refresh').addEventListener('click', refresh);
    el('btn-audits-select-ready').addEventListener('click', () => {
      for (const item of entries) el(`audit-select-${item.id}`).checked = item.ready;
      syncSelection();
    });
    el('btn-audits-clear').addEventListener('click', () => {
      document.querySelectorAll('.audit-checkbox').forEach(node => { node.checked = false; });
      syncSelection();
    });
    el('btn-run-audits').addEventListener('click', run);
    el('btn-cancel-audits').addEventListener('click', () => controller?.abort());
  });
})();
