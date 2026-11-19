// Vivo folders in the web tool: classic (original machine) or one root (team machines).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function load(initial, fetchAnswer) {
  const storage = new Map(Object.entries(initial));
  const localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
    key: index => [...storage.keys()][index] ?? null,
    get length() { return storage.size; },
  };
  const status = {className: '', textContent: ''};
  const reloads = [];
  const context = vm.createContext({
    document: {addEventListener() {}, getElementById: id => (id === 'vivo-root-status' ? status : null)},
    window: {location: {protocol: 'http:', origin: 'http://127.0.0.1:8765', reload: () => reloads.push(1)}, addEventListener() {}},
    fetch: () => Promise.resolve({json: () => Promise.resolve(fetchAnswer || {})}),
    localStorage,
    console,
  });
  vm.runInContext(fs.readFileSync('web-tool/app.js', 'utf8'), context);
  return {storage, status, reloads, run: code => vm.runInContext(code, context)};
}

(async () => {
  // Original machine: nothing saved = classic folders, same defaults as always.
  const classic = load({});
  assert.equal(classic.run('VIVO_ROOT'), 'classic');
  assert.equal(classic.run('DEFAULT_DUMP_DIR'), 'C:/Dumps/todos_enms');
  assert.equal(classic.run('DEFAULT_REFERENCE_DIR'), 'C:/Camilo');

  // Team machine: one root, Referencias instead of Camilo.
  const team = load({downloader_vivo_root: 'D:\\Equipe\\Vivo\\'});
  assert.equal(team.run('VIVO_ROOT'), 'D:/Equipe/Vivo');
  assert.equal(team.run('DEFAULT_DUMP_DIR'), 'D:/Equipe/Vivo/Dumps/todos_enms');
  assert.equal(team.run('DEFAULT_PROCESSED_DIR'), 'D:/Equipe/Vivo/Dumps/LTE_Total');
  assert.equal(team.run('DEFAULT_REFERENCE_DIR'), 'D:/Equipe/Vivo/Referencias');
  assert.equal(team.run('VIVO_FOLDERS.reports'), 'D:/Equipe/Vivo/Relatorios');
  assert.match(team.run("claroRootProblem('D:/Equipe/Vivo/Claro')"), /overlaps the Vivo folder D:\/Equipe\/Vivo/);
  assert.match(team.run("vivoRootProblem('C:/Claro_Reports/x')"), /overlaps the Claro folder/);

  // Classic -> root: every saved Vivo folder moves role by role; Claro and other folders stay.
  const move = load({
    downloader_vivo_root: 'classic',
    downloader_last_output_dir: 'C:/Dumps/todos_enms/W45',
    downloader_parser_processed_dir: 'C:\\Dumps\\LTE_Total',
    downloader_site_list_save_dir: 'C:/Camilo',
    downloader_weekly_vivo_dir: 'C:/Vivo Reports',
    downloader_other: 'D:/Other/folder',
    'claro:downloader_claro_processed_dir': 'C:/Claro_Reports/MOs',
    downloader_enm_profiles: JSON.stringify({profiles: [{name: 'p', output_dir: 'C:/Dumps/todos_enms'}]}),
  });
  move.run("applyVivoRoot('E:/VD')");
  assert.equal(move.storage.get('downloader_vivo_root'), 'E:/VD');
  assert.equal(move.storage.get('downloader_last_output_dir'), 'E:/VD/Dumps/todos_enms/W45');
  assert.equal(move.storage.get('downloader_parser_processed_dir'), 'E:/VD/Dumps/LTE_Total');
  assert.equal(move.storage.get('downloader_site_list_save_dir'), 'E:/VD/Referencias');
  assert.equal(move.storage.get('downloader_weekly_vivo_dir'), 'E:/VD/Relatorios');
  assert.equal(move.storage.get('downloader_other'), 'D:/Other/folder');
  assert.equal(move.storage.get('claro:downloader_claro_processed_dir'), 'C:/Claro_Reports/MOs');
  assert.equal(JSON.parse(move.storage.get('downloader_enm_profiles')).profiles[0].output_dir, 'E:/VD/Dumps/todos_enms');
  assert.equal(move.reloads.length, 1);

  // And back: root -> classic.
  const back = load({downloader_vivo_root: 'E:/VD', downloader_site_list_save_dir: 'E:/VD/Referencias'});
  back.run("applyVivoRoot('classic')");
  assert.equal(back.storage.get('downloader_vivo_root'), 'classic');
  assert.equal(back.storage.get('downloader_site_list_save_dir'), 'C:/Camilo');

  // A Vivo root inside the Claro root is refused and nothing is saved.
  const bad = load({downloader_vivo_root: 'classic'});
  bad.run("applyVivoRoot('C:/Claro_Reports/Vivo')");
  assert.equal(bad.storage.get('downloader_vivo_root'), 'classic');
  assert.match(bad.status.textContent, /overlaps the Claro folder/);

  // First use: a browser with Vivo settings is the original machine -> classic, no server call.
  const used = load({downloader_enm_list: '[]'});
  assert.equal(used.run('initVivoLayout()'), true);
  assert.equal(used.storage.get('downloader_vivo_root'), 'classic');
  // A brand-new browser asks the server (here: no classic folders on this machine).
  const fresh = load({}, {suggested: 'C:/Vivo_Downloader'});
  assert.equal(fresh.run('initVivoLayout()'), true);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(fresh.storage.get('downloader_vivo_root'), 'C:/Vivo_Downloader');
  assert.equal(fresh.reloads.length, 1);
  // Chosen already: nothing happens.
  assert.equal(load({downloader_vivo_root: 'classic'}).run('initVivoLayout()'), false);

  console.log('PASS: Vivo classic folders unchanged; team root, role-by-role move, Claro guard and first-use choice.');
})().catch(error => { console.error(error); process.exit(1); });
