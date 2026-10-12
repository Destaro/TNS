// Headless driver for the TGExtension (Victorian Tools) language server: runs its full-mod report.
// usage: node run_report.js <tgext_dir> <workspace_dir> <out.json> [gamePath] [modName]
const path = require('path');
const cp = require('child_process');
const fs = require('fs');
const [, , extDirArg, workspace, outFile, gamePath = '', modName = ''] = process.argv;
const extDir = path.resolve(extDirArg);
const rpc = require(path.join(extDir, 'node_modules', 'vscode-jsonrpc', 'lib', 'node', 'main.js'));

const child = cp.spawn(process.execPath, ['--max-old-space-size=6144', path.join(extDir, 'dist', 'server.js'), '--stdio'], { stdio: ['pipe', 'pipe', 'inherit'] });
const conn = rpc.createMessageConnection(new rpc.StreamMessageReader(child.stdout), new rpc.StreamMessageWriter(child.stdin));
const settings = {
  gamePath, activeMods: modName ? [modName] : [], encoding: 'windows-1252',
  validation: { enable: true, delay: 300 }, index: { onStartup: false, rebuildDelay: 1000 },
};
conn.onRequest('workspace/configuration', (p) => p.items.map(() => settings));
conn.onRequest('client/registerCapability', () => null);
conn.onRequest('window/workDoneProgress/create', () => null);
conn.onNotification('window/logMessage', (m) => process.stderr.write('[server] ' + m.message + '\n'));
conn.onNotification('textDocument/publishDiagnostics', () => {});
conn.onUnhandledNotification(() => {});
conn.listen();

(async () => {
  const uri = 'file://' + path.resolve(workspace);
  await conn.sendRequest('initialize', {
    processId: process.pid, rootUri: uri, workspaceFolders: [{ uri, name: 'ws' }],
    capabilities: { workspace: { configuration: true, workspaceFolders: true } },
  });
  conn.sendNotification('initialized', {});
  await new Promise((r) => setTimeout(r, 3000));
  const t = Date.now();
  const res = await conn.sendRequest('victorianTools/fullReport', { workspaceFolders: [path.resolve(workspace)], mods: modName ? [modName] : [] });
  fs.writeFileSync(outFile, JSON.stringify(res));
  process.stderr.write(`report done in ${Date.now() - t}ms\n`);
  child.kill(); process.exit(0);
})().catch((e) => { console.error(e); child.kill(); process.exit(1); });
