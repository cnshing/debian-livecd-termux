// Run with the packaged Node: SERVER/node tests/code-oss/server-smoke.cjs SERVER
// Also works with: qemu-aarch64 -L SYSROOT SERVER/node ...
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');

const server = path.resolve(process.argv[2]);
const load = createRequire(path.join(server, 'package.json'));
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'code-oss-server-smoke-'));
const deadline = setTimeout(() => { console.error('FAIL: smoke test timed out'); process.exit(1); }, 30000);
const pass = name => console.log(`PASS ${name}`);

async function main() {
    const product = load('./product.json');
    const build = load('./build-info.json');
    assert.equal(process.platform, 'linux');
    assert.equal(process.arch, build.arch);
    assert.equal(process.versions.node, build.nodeVersion);
    assert.equal(product.commit, build.commit);
    assert.equal(product.version, build.version);
    assert.equal(product.extensionsGallery.serviceUrl, 'https://open-vsx.org/vscode/gallery');
    pass('runtime and editor identity');

    const spdlog = load('@vscode/spdlog');
    const logfile = path.join(scratch, 'test.log');
    const logger = await spdlog.createRotatingLogger('smoke', logfile, 1024 * 1024, 1);
    logger.info('native logging works');
    logger.flush();
    logger.drop();
    assert.match(fs.readFileSync(logfile, 'utf8'), /native logging works/);
    pass('spdlog writes a log');

    const sqlite = load('@vscode/sqlite3');
    const db = new sqlite.Database(path.join(scratch, 'test.sqlite'));
    const run = sql => new Promise((resolve, reject) => db.run(sql, error => error ? reject(error) : resolve()));
    await run('CREATE VIRTUAL TABLE search USING fts5(text)');
    await run("INSERT INTO search VALUES ('native database works')");
    const row = await new Promise((resolve, reject) => db.get(
        "SELECT text FROM search WHERE search MATCH 'database'", (error, row) => error ? reject(error) : resolve(row)));
    assert.equal(row.text, 'native database works');
    await new Promise((resolve, reject) => db.close(error => error ? reject(error) : resolve()));
    pass('sqlite writes, reads and searches with FTS5');

    const watcher = load('@parcel/watcher');
    const watched = path.join(scratch, 'watched');
    fs.mkdirSync(watched);
    let observed;
    const event = new Promise((resolve, reject) => { observed = { resolve, reject }; });
    const subscription = await watcher.subscribe(watched, (error, events) => {
        if (error) observed.reject(error);
        else if (events.some(e => e.path === path.join(watched, 'probe'))) observed.resolve();
    });
    try {
        fs.writeFileSync(path.join(watched, 'probe'), 'file watching works');
        await event;
    } finally {
        await subscription.unsubscribe();
    }
    pass('parcel watcher receives a real file event');

    const pty = load('node-pty');
    const terminal = pty.spawn('/bin/sh', ['-c', 'printf native-terminal-ok'], { env: process.env });
    let output = '';
    terminal.onData(data => { output += data; });
    const status = await new Promise(resolve => terminal.onExit(resolve));
    assert.equal(status.exitCode, 0);
    assert.match(output, /native-terminal-ok/);
    pass('node-pty runs a shell');

    // These packages use JS on Linux; no deviceid or fs-copyfile addon is needed.
    assert.equal(typeof load('@vscode/deviceid').getDeviceId, 'function');
    const copy = await import(pathToFileURL(load.resolve('@vscode/fs-copyfile')).href);
    await copy.copyFile(logfile, path.join(scratch, 'copy.log'));
    assert.equal(fs.readFileSync(path.join(scratch, 'copy.log'), 'utf8'), fs.readFileSync(logfile, 'utf8'));
    pass('Linux deviceid and file copy load');

    assert.equal(typeof load('@vscode/native-watchdog').start, 'function');
    load('node-ovsx-sign');
    pass('watchdog and Open VSX verifier load');

    const koffi = load('koffi');
    const getpid = koffi.load(null).func('int getpid()');
    assert.equal(getpid(), process.pid);
    pass('target Koffi prebuild calls libc');
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
    clearTimeout(deadline);
    fs.rmSync(scratch, { recursive: true, force: true });
});
