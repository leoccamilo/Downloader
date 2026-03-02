/**
 * File Viewer - view and filter TXT, CSV, XLSX in browser.
 * Supports multi-sheet XLSX navigation.
 * Export filtered data to CSV, TXT, or XLSX.
 */

(function () {
  const MAX_ROWS = 50000;
  const DISPLAY_ROWS = 5000;
  const DEFAULT_DISPLAY_COLS = 150;
  const COLS_STEP = 100;
  let fullData = { headers: [], rows: [] };
  let filteredRows = [];
  let columnFilters = {};
  let loadId = 0;
  let displayColsLimit = DEFAULT_DISPLAY_COLS;

  let xlsxWorkbook = null;
  let xlsxSheetNames = [];
  let activeSheetIndex = 0;

  const inputEl = document.getElementById('file-viewer-input');
  const btnSelect = document.getElementById('btn-file-viewer-select');
  const btnExport = document.getElementById('btn-export-filtered');
  const btnMoreCols = document.getElementById('btn-file-viewer-more-cols');
  const btnCloseFile = document.getElementById('btn-file-viewer-close');
  const placeholder = document.getElementById('file-viewer-placeholder');
  const container = document.getElementById('file-viewer-container');
  const thead = document.getElementById('file-viewer-thead');
  const tbody = document.getElementById('file-viewer-tbody');
  const nameEl = document.getElementById('file-viewer-name');
  const statsEl = document.getElementById('file-viewer-stats');
  const sheetTabsEl = document.getElementById('file-viewer-sheet-tabs');

  if (!inputEl || !btnSelect) return;

  btnSelect.addEventListener('click', () => inputEl.click());
  inputEl.addEventListener('change', onFileSelected);

  document.querySelectorAll('[data-export]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      const fmt = el.getAttribute('data-export');
      if (fmt && filteredRows.length > 0) exportFiltered(fmt);
    });
  });

  if (btnMoreCols) btnMoreCols.addEventListener('click', showMoreColumns);
  if (btnCloseFile) btnCloseFile.addEventListener('click', closeFile);

  function showMoreColumns() {
    if (!fullData.headers) return;
    const total = fullData.headers.length;
    if (displayColsLimit >= total) return;
    displayColsLimit = Math.min(displayColsLimit + COLS_STEP, total);
    render();
  }

  function closeFile() {
    fullData = { headers: [], rows: [] };
    filteredRows = [];
    columnFilters = {};
    displayColsLimit = DEFAULT_DISPLAY_COLS;
    xlsxWorkbook = null;
    xlsxSheetNames = [];
    activeSheetIndex = 0;
    if (btnExport) btnExport.disabled = true;
    if (btnMoreCols) btnMoreCols.classList.add('d-none');
    if (btnCloseFile) btnCloseFile.classList.add('d-none');
    if (sheetTabsEl) { sheetTabsEl.innerHTML = ''; sheetTabsEl.classList.add('d-none'); sheetTabsEl.classList.remove('d-flex'); }
    nameEl.textContent = 'No file loaded';
    statsEl.textContent = '--';
    render();
  }

  function onFileSelected(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    loadId += 1;
    const thisLoadId = loadId;

    const existingModal = document.getElementById('filterModal');
    if (existingModal) {
      const bsModal = bootstrap.Modal.getInstance(existingModal);
      if (bsModal) try { bsModal.dispose(); } catch (_) {}
      existingModal.remove();
      document.querySelector('.modal-backdrop')?.remove();
      document.body.classList.remove('modal-open');
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    }

    btnSelect.disabled = true;
    btnExport.disabled = true;
    nameEl.textContent = file.name + ' — Loading...';
    statsEl.textContent = 'Loading...';
    placeholder.classList.remove('d-none');
    container.classList.add('d-none');
    placeholder.innerHTML = '<i class="bi bi-hourglass-split"></i><p class="mt-2 mb-0">Loading file...</p>';
    if (sheetTabsEl) { sheetTabsEl.innerHTML = ''; sheetTabsEl.classList.add('d-none'); sheetTabsEl.classList.remove('d-flex'); }

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    const reader = new FileReader();
    reader.onload = (ev) => {
      if (thisLoadId !== loadId) return;
      const doParse = () => {
        if (thisLoadId !== loadId) return;
        try {
          if (ext === 'xlsx' || ext === 'xls') {
            parseXlsx(ev.target.result);
          } else {
            xlsxWorkbook = null;
            xlsxSheetNames = [];
            if (sheetTabsEl) { sheetTabsEl.innerHTML = ''; sheetTabsEl.classList.add('d-none'); sheetTabsEl.classList.remove('d-flex'); }
            parseText(ev.target.result, ext === 'csv');
          }
        } catch (err) {
          if (thisLoadId !== loadId) return;
          alert('Error parsing file: ' + err.message);
        } finally {
          if (thisLoadId === loadId) {
            btnSelect.disabled = false;
            nameEl.textContent = file.name;
          }
        }
      };
      setTimeout(doParse, 0);
    };
    reader.onerror = () => {
      if (thisLoadId === loadId) {
        btnSelect.disabled = false;
        nameEl.textContent = file.name;
        alert('Error reading file.');
      }
    };
    if (ext === 'xlsx' || ext === 'xls') {
      reader.readAsArrayBuffer(file);
    } else {
      reader.readAsText(file, 'ISO-8859-1');
    }
    inputEl.value = '';
  }

  function parseText(text, isCsv) {
    const lines = text.split(/\r?\n/).filter(l => l.length > 0);
    if (lines.length === 0) {
      fullData = { headers: [], rows: [] };
      render();
      return;
    }
    const sep = isCsv ? detectCsvDelimiter(lines[0]) : '\t';
    const headers = parseLine(lines[0], sep);
    const rows = [];
    for (let i = 1; i < Math.min(lines.length, MAX_ROWS + 1); i++) {
      rows.push(parseLine(lines[i], sep));
    }
    if (lines.length > MAX_ROWS + 1) {
      console.warn('Showing first ' + MAX_ROWS + ' rows. Total: ' + (lines.length - 1));
    }
    fullData = { headers, rows };
    columnFilters = {};
    displayColsLimit = DEFAULT_DISPLAY_COLS;
    applyFilters();
    render();
    btnExport.disabled = false;
    if (btnMoreCols) btnMoreCols.classList.remove('d-none');
    if (btnCloseFile) btnCloseFile.classList.remove('d-none');
  }

  function detectCsvDelimiter(line) {
    const tabCount = (line.match(/\t/g) || []).length;
    const commaCount = (line.match(/,/g) || []).length;
    return tabCount >= commaCount ? '\t' : ',';
  }

  function parseLine(line, sep) {
    const out = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        inQuotes = !inQuotes;
      } else if (!inQuotes && c === sep) {
        out.push(cur.trim());
        cur = '';
      } else {
        cur += c;
      }
    }
    out.push(cur.trim());
    return out;
  }

  function parseXlsx(arrayBuffer) {
    if (typeof XLSX === 'undefined') {
      alert('XLSX library not loaded. Add: <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"><\/script>');
      return;
    }
    xlsxWorkbook = XLSX.read(arrayBuffer, { type: 'array' });
    xlsxSheetNames = xlsxWorkbook.SheetNames;
    activeSheetIndex = 0;
    loadXlsxSheet(0);
    renderSheetTabs();
  }

  function loadXlsxSheet(index) {
    if (!xlsxWorkbook || index < 0 || index >= xlsxSheetNames.length) return;
    activeSheetIndex = index;
    const ws = xlsxWorkbook.Sheets[xlsxSheetNames[index]];
    const arr = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' });
    if (arr.length === 0) {
      fullData = { headers: [], rows: [] };
      columnFilters = {};
      displayColsLimit = DEFAULT_DISPLAY_COLS;
      applyFilters();
      render();
      return;
    }
    const headers = arr[0].map(String);
    const rows = [];
    for (let i = 1; i < Math.min(arr.length, MAX_ROWS + 1); i++) {
      const r = arr[i];
      rows.push(headers.map((_, j) => (r[j] != null ? String(r[j]) : '')));
    }
    if (arr.length > MAX_ROWS + 1) {
      console.warn('Showing first ' + MAX_ROWS + ' rows.');
    }
    fullData = { headers, rows };
    columnFilters = {};
    displayColsLimit = DEFAULT_DISPLAY_COLS;
    applyFilters();
    render();
    btnExport.disabled = false;
    if (btnMoreCols) btnMoreCols.classList.remove('d-none');
    if (btnCloseFile) btnCloseFile.classList.remove('d-none');
  }

  function renderSheetTabs() {
    if (!sheetTabsEl) return;
    if (xlsxSheetNames.length <= 1) {
      sheetTabsEl.innerHTML = '';
      sheetTabsEl.classList.add('d-none');
      sheetTabsEl.classList.remove('d-flex');
      return;
    }
    sheetTabsEl.classList.remove('d-none');
    sheetTabsEl.classList.add('d-flex');
    sheetTabsEl.innerHTML = '';
    xlsxSheetNames.forEach((name, i) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = name;
      btn.className = i === activeSheetIndex
        ? 'btn btn-sm btn-light fw-bold'
        : 'btn btn-sm btn-outline-light';
      btn.onclick = () => {
        if (i === activeSheetIndex) return;
        loadXlsxSheet(i);
        renderSheetTabs();
      };
      sheetTabsEl.appendChild(btn);
    });
  }

  function applyFilters() {
    if (!fullData.rows.length) {
      filteredRows = [];
      return;
    }
    filteredRows = fullData.rows.filter(row => {
      for (let c = 0; c < fullData.headers.length; c++) {
        const flt = columnFilters[c];
        if (flt && flt.size > 0) {
          const v = (row[c] ?? '').toString();
          if (!flt.has(v)) return false;
        }
      }
      return true;
    });
  }

  function getUniqueValues(colIndex) {
    const s = new Set();
    fullData.rows.forEach(row => {
      s.add((row[colIndex] ?? '').toString());
    });
    return Array.from(s).sort((a, b) => String(a).localeCompare(String(b)));
  }

  const placeholderDefaultHtml = '<i class="bi bi-file-earmark-spreadsheet display-4"></i><p class="mt-2 mb-0">Select a file (TXT, CSV or XLSX) to view and filter. Use column headers to filter like Excel.</p>';

  function render() {
    if (!fullData.headers || fullData.headers.length === 0) {
      placeholder.innerHTML = placeholderDefaultHtml;
      placeholder.classList.remove('d-none');
      container.classList.add('d-none');
      statsEl.textContent = 'No data';
      if (btnMoreCols) btnMoreCols.classList.add('d-none');
      if (btnCloseFile) btnCloseFile.classList.add('d-none');
      return;
    }
    placeholder.classList.add('d-none');
    container.classList.remove('d-none');

    thead.innerHTML = '';
    tbody.innerHTML = '';

    const numCols = Math.min(fullData.headers.length, displayColsLimit);
    const tr = document.createElement('tr');
    for (let i = 0; i < numCols; i++) {
      const h = fullData.headers[i];
      const th = document.createElement('th');
      th.className = 'position-relative pe-4';
      th.textContent = h;

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-link btn-sm p-0 position-absolute end-0 top-50 translate-middle-y text-white-50';
      btn.innerHTML = '<i class="bi bi-funnel"></i>';
      btn.title = 'Filter column';
      btn.onclick = () => openFilterModal(i, h);
      th.appendChild(btn);
      tr.appendChild(th);
    }
    thead.appendChild(tr);

    const displayRows = filteredRows.slice(0, DISPLAY_ROWS);
    const truncated = filteredRows.length > DISPLAY_ROWS;
    const fragment = document.createDocumentFragment();
    for (let r = 0; r < displayRows.length; r++) {
      const row = displayRows[r];
      const rowTr = document.createElement('tr');
      for (let i = 0; i < numCols; i++) {
        const td = document.createElement('td');
        td.textContent = (row[i] ?? '').toString();
        td.style.maxWidth = '200px';
        td.style.overflow = 'hidden';
        td.style.textOverflow = 'ellipsis';
        td.title = td.textContent;
        rowTr.appendChild(td);
      }
      fragment.appendChild(rowTr);
    }
    tbody.appendChild(fragment);

    let stats = `${filteredRows.length} rows`;
    if (filteredRows.length !== fullData.rows.length) {
      stats += ` (filtered from ${fullData.rows.length})`;
    }
    if (truncated) stats += ` — showing first ${DISPLAY_ROWS}`;
    if (numCols < fullData.headers.length) stats += ` | ${numCols}/${fullData.headers.length} cols`;
    if (xlsxSheetNames.length > 1) {
      stats += ` | Sheet: ${xlsxSheetNames[activeSheetIndex]}`;
    }
    statsEl.textContent = stats;

    if (btnMoreCols) {
      if (numCols < fullData.headers.length) {
        btnMoreCols.classList.remove('d-none');
        const remaining = fullData.headers.length - displayColsLimit;
        btnMoreCols.innerHTML = remaining <= COLS_STEP
          ? '<i class="bi bi-arrows-expand"></i> Show all'
          : `<i class="bi bi-arrows-expand"></i> +${COLS_STEP} cols`;
      } else {
        btnMoreCols.classList.add('d-none');
      }
    }
  }

  function openFilterModal(colIndex, colName) {
    const vals = getUniqueValues(colIndex);
    const current = columnFilters[colIndex] || new Set();
    const modalHtml = `
      <div class="modal fade" id="filterModal" tabindex="-1">
        <div class="modal-dialog modal-dialog-scrollable">
          <div class="modal-content">
            <div class="modal-header">
              <h6 class="modal-title">Filter: ${escapeHtml(colName)}</h6>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <input type="text" class="form-control form-control-sm mb-2" id="filter-search" placeholder="Search...">
              <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="filter-select-all" checked>
                <label class="form-check-label" for="filter-select-all">Select all</label>
              </div>
              <div id="filter-options" style="max-height: 300px; overflow-y: auto;"></div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
              <button type="button" class="btn btn-sm btn-primary" id="filter-apply">Apply</button>
            </div>
          </div>
        </div>
      </div>`;

    let existing = document.getElementById('filterModal');
    if (existing) existing.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = new bootstrap.Modal(document.getElementById('filterModal'));
    const optionsEl = document.getElementById('filter-options');
    const searchEl = document.getElementById('filter-search');
    const selectAllEl = document.getElementById('filter-select-all');
    const applyBtn = document.getElementById('filter-apply');

    function renderOptions(filterText) {
      const lower = (filterText || '').toLowerCase();
      const list = lower ? vals.filter(v => String(v).toLowerCase().includes(lower)) : vals;
      optionsEl.innerHTML = list.map(v => {
        const checked = current.size === 0 || current.has(v);
        return `<div class="form-check">
          <input class="form-check-input filter-opt" type="checkbox" value="${escapeHtml(v)}" ${checked ? 'checked' : ''}>
          <label class="form-check-label text-truncate d-block" style="max-width: 300px;">${escapeHtml(v) || '(empty)'}</label>
        </div>`;
      }).join('');
    }
    renderOptions();

    searchEl.oninput = () => renderOptions(searchEl.value);
    selectAllEl.onchange = () => {
      optionsEl.querySelectorAll('.filter-opt').forEach(cb => cb.checked = selectAllEl.checked);
    };

    applyBtn.onclick = () => {
      const selected = new Set();
      optionsEl.querySelectorAll('.filter-opt:checked').forEach(cb => selected.add(cb.value));
      if (selected.size === vals.length) {
        columnFilters[colIndex] = null;
      } else {
        columnFilters[colIndex] = selected;
      }
      applyFilters();
      render();
      modal.hide();
    };

    modal.show();
    modal._element.addEventListener('hidden.bs.modal', () => modal._element.remove(), { once: true });
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function exportFiltered(format) {
    if (filteredRows.length === 0) return;
    const sep = format === 'txt' ? '\t' : ',';
    const ext = format === 'xlsx' ? 'xlsx' : format;
    const baseName = (nameEl.textContent || 'export').replace(/\.[^.]+$/, '');
    const sheetSuffix = xlsxSheetNames.length > 1 ? '_' + xlsxSheetNames[activeSheetIndex] : '';
    const fileName = baseName + sheetSuffix + '.' + ext;

    const outputDirEl = document.getElementById('file-viewer-output-dir');
    const outputDir = outputDirEl ? outputDirEl.value.trim() : '';

    function saveViaServer(contentBase64, fName, fallbackDownload) {
      if (!outputDir) {
        fallbackDownload();
        return;
      }
      fetch('/api/save-file-viewer-export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          output_dir: outputDir,
          filename: fName,
          content_base64: contentBase64
        })
      }).then(r => r.json()).then(data => {
        if (data.ok) {
          alert('Saved to ' + (data.path || outputDir + '/' + fName));
        } else {
          console.warn('Server save failed:', data.error);
          fallbackDownload();
        }
      }).catch(err => {
        console.warn('Server unavailable, downloading:', err);
        fallbackDownload();
      });
    }

    if (format === 'xlsx') {
      if (typeof XLSX === 'undefined') {
        alert('XLSX export requires SheetJS. Falling back to CSV download.');
        downloadCsvTxt(',', baseName + sheetSuffix + '.csv');
        return;
      }
      const wsData = [fullData.headers, ...filteredRows];
      const ws = XLSX.utils.aoa_to_sheet(wsData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, xlsxSheetNames[activeSheetIndex] || 'Sheet1');
      const xlsxBase64 = XLSX.write(wb, { bookType: 'xlsx', type: 'base64' });
      saveViaServer(xlsxBase64, fileName, () => XLSX.writeFile(wb, fileName));
    } else {
      const BOM = '\uFEFF';
      const headerLine = fullData.headers.map(h => escapeCsv(h, sep)).join(sep);
      const lines = filteredRows.map(row =>
        fullData.headers.map((_, i) => escapeCsv((row[i] ?? '').toString(), sep)).join(sep)
      );
      const content = BOM + headerLine + '\n' + lines.join('\n');
      const contentBase64 = btoa(unescape(encodeURIComponent(content)));
      saveViaServer(contentBase64, fileName, () => downloadCsvTxt(sep, fileName));
    }
  }

  function downloadCsvTxt(sep, fileName) {
    const BOM = '\uFEFF';
    const headerLine = fullData.headers.map(h => escapeCsv(h, sep)).join(sep);
    const lines = filteredRows.map(row =>
      fullData.headers.map((_, i) => escapeCsv((row[i] ?? '').toString(), sep)).join(sep)
    );
    const content = BOM + headerLine + '\n' + lines.join('\n');
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fileName;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function escapeCsv(v, sep) {
    if (v.includes(sep) || v.includes('"') || v.includes('\n') || v.includes('\r')) {
      return '"' + v.replace(/"/g, '""') + '"';
    }
    return v;
  }
})();
