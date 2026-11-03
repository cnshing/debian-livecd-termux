// Installed only in the scratch server's extension directory by test-code-oss.py.
const fs = require('fs');
const os = require('os');
const path = require('path');
const vscode = require('vscode');

exports.activate = context => {
    context.subscriptions.push(vscode.commands.registerCommand('serverProbe.run', async () => {
        const root = vscode.workspace.workspaceFolders[0].uri.fsPath;
        const files = await vscode.workspace.findFiles('README.md', '**/.server/**', 20);
        fs.writeFileSync(path.join(root, 'server-probe.json'), JSON.stringify({
            hostname: os.hostname(), arch: process.arch, platform: process.platform,
            remoteName: vscode.env.remoteName,
            files: files.map(file => path.relative(root, file.fsPath)),
            readme: fs.readFileSync(path.join(root, 'README.md'), 'utf8'),
        }));
    }));
};
