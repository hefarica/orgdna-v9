'use strict';
// Collect names without importing Playwright, starting servers, or running tests.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const PAGES = ['inicio','organigrama','perfiles','council','habilidades','modelos','repositorio','exportaciones','registro'];
const names = [];
for (const file of fs.readdirSync(__dirname).filter(f => f.endsWith('.spec.cjs'))) {
  const test = (title, body) => { if (typeof body !== 'function') throw new Error('Missing test body'); names.push({ file, title, status: 'NOT_RUN' }); };
  const context = { require: name => {
    if (name === './fixtures.cjs') return { test, expect: {}, PAGES };
    if (name === './control-matrix.json') return JSON.parse(fs.readFileSync(path.join(__dirname,'control-matrix.json')));
    throw new Error('Unexpected import in declaration-only check: ' + name);
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,file),'utf8'), context, { filename: file, timeout: 1000 });
}
const report = { kind: 'authored-case-inventory', browser_execution: 'NOT_RUN', count: names.length, tests: names };
if (process.argv.includes('--write')) fs.writeFileSync(path.join(__dirname,'authored-cases.json'), JSON.stringify(report,null,2)+'\n');
process.stdout.write(JSON.stringify(report,null,2)+'\n');
