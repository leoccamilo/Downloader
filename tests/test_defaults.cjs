const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const storage = new Map();
const context = vm.createContext({
  document: {addEventListener() {}},
  window: {location: {protocol: 'http:', host: '127.0.0.1:8765', hostname: '127.0.0.1', port: '8765'}, addEventListener() {}},
  localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
  console,
});
vm.runInContext(fs.readFileSync('web-tool/app.js', 'utf8'), context);
storage.set('downloader_last_output_dir', 'C:\\Downloader\\data\\input');
storage.set('downloader_parser_output_dir', 'C:/Downloader/data/output');
storage.set('downloader_parser_enriched_dir', 'C:/Downloader/data/enriched');
storage.set('downloader_enm_profiles', JSON.stringify({profiles: [{
  name: 'Monday', output_dir: 'C:/eNB_Fake/data/input', enms: {
    ENMBARA: {username: 'fixture', password: 'fixture'},
    ENMCTPA: {username: 'fixture', password: 'fixture'},
  },
}], last_used_profile: 'Monday'}));
vm.runInContext('migrateWeeklyDefaults()', context);
assert.equal(storage.get('downloader_last_output_dir'), 'C:/Dumps/todos_enms');
assert.equal(storage.get('downloader_parser_output_dir'), 'C:/Dumps/todos_enms');
assert.equal(storage.get('downloader_parser_enriched_dir'), 'C:/Camilo');
const migrated = JSON.parse(storage.get('downloader_enm_profiles')).profiles[0];
assert.equal(migrated.output_dir, 'C:/Dumps/todos_enms');
assert.equal(migrated.enms.ENMBARA.include, true);
assert.equal(migrated.enms.ENMCTPA.include, false);
assert.equal(migrated.enms.ENMBARA.password, 'fixture');
assert.equal(vm.runInContext("getEnmIncluded('ENMCTPB')", context), true);
assert.equal(vm.runInContext("getEnmIncluded('ENMCTPA')", context), false);
storage.set('downloader_enm_selection', JSON.stringify({ENMCTPB: false}));
assert.equal(vm.runInContext("getEnmIncluded('ENMCTPB')", context), false);
storage.set('downloader_last_output_dir', 'D:/Custom/dumps');
vm.runInContext('migrateWeeklyDefaults()', context);
assert.equal(storage.get('downloader_last_output_dir'), 'D:/Custom/dumps');
console.log('PASS: legacy paths and profiles migrate; credentials and explicit custom settings survive.');
