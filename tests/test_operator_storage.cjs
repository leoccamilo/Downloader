// Claro mode: own storage namespace, Claro defaults, ENM list and node filter by municipality.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function load(initial) {
  const storage = new Map(Object.entries(initial));
  const localStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
    key: index => [...storage.keys()][index] ?? null,
    get length() { return storage.size; },
  };
  const context = vm.createContext({
    document: {addEventListener() {}},
    window: {location: {protocol: 'http:', origin: 'http://127.0.0.1:8765'}, addEventListener() {}},
    localStorage,
    console,
  });
  vm.runInContext(fs.readFileSync('web-tool/app.js', 'utf8'), context);
  return {storage, run: code => vm.runInContext(code, context)};
}

// Vivo (no operator saved): historical keys and defaults are untouched.
const vivo = load({});
assert.equal(vivo.run('OPERATOR'), 'vivo');
assert.equal(vivo.run('DEFAULT_DUMP_DIR'), 'C:/Dumps/todos_enms');
vivo.run("opStorage.setItem('downloader_last_output_dir', 'C:/Dumps/x')");
assert.equal(vivo.storage.get('downloader_last_output_dir'), 'C:/Dumps/x');
assert.deepEqual(JSON.parse(vivo.run('JSON.stringify(getEnmList().map(e => e.id))')), ['ENMBARA', 'ENMBARB', 'ENMCTPB', 'ENMCTPA']);

// Claro: every key under "claro:", folders under the editable root, own ENM list.
const claro = load({
  downloader_operator: 'claro',
  'claro:downloader_claro_root': 'D:\\PR\\Reports\\',
  downloader_enm_list: JSON.stringify([{id: 'ENMBARA', url: 'https://enmbara.ran.redestlf.br/'}]),
});
assert.equal(claro.run('OPERATOR'), 'claro');
assert.equal(claro.run('CLARO_ROOT'), 'D:/PR/Reports');
assert.equal(claro.run('DEFAULT_DUMP_DIR'), 'D:/PR/Reports/Dumps');
assert.equal(claro.run('DEFAULT_PROCESSED_DIR'), 'D:/PR/Reports/MOs');
assert.deepEqual(JSON.parse(claro.run('JSON.stringify(getEnmList().map(e => [e.id, e.url]))')), [['ENMSANTURCE', 'https://renmsanturce.prt.local/']]);
assert.ok(claro.storage.has('claro:downloader_enm_list'), 'Claro ENM list saved in its own namespace');
assert.equal(JSON.parse(claro.storage.get('downloader_enm_list'))[0].id, 'ENMBARA', 'Vivo ENM list untouched');
assert.equal(claro.run("getEnmIncluded('ENMSANTURCE')"), true);
claro.run('migrateWeeklyDefaults()');
assert.equal(claro.storage.get('claro:downloader_last_output_dir'), undefined, 'Vivo migration never runs for Claro');

// Scope: network = every node; region and municipality become node-name wildcards.
claro.run(`claroGeography = {regions: ['Metro East', 'South'], municipalities: [
  {code: 'CAR', name: 'Carolina', region: 'Metro East'}, {code: 'SJU', name: 'San Juan', region: 'Metro East'},
  {code: 'PON', name: 'Ponce', region: 'South'}]};`);
assert.equal(claro.run('claroSitesString()'), '*');
claro.run("claroScopeState = {mode: 'region', regions: ['Metro East'], municipalities: []}");
assert.equal(claro.run('claroSitesString()'), 'CAR*;SJU*');
assert.equal(claro.run('getScope()'), 'region');
claro.run("claroScopeState = {mode: 'municipality', regions: [], municipalities: ['PON', 'XXX', 'CAR']}");
assert.equal(claro.run('claroSitesString()'), 'CAR*;PON*', 'unknown codes are ignored');
claro.run("claroScopeState = {mode: 'region', regions: [], municipalities: []}");
assert.equal(claro.run('claroSitesString()'), '');

// Root folder: must not be a drive root nor overlap the Vivo folders.
assert.match(claro.run("claroRootProblem('C:/')"), /drive root/);
assert.match(claro.run("claroRootProblem('C:/Camilo/PR')"), /overlaps the Vivo folder/);
assert.equal(claro.run("claroRootProblem('C:/Claro_Reports')"), '');
console.log('PASS: Claro namespace, defaults, ENM list, scope wildcards and root checks; Vivo keys untouched.');
