// Test fixture: writes through the editor's real secret storage, and reports to a file.
const fs = require('fs');
const vscode = require('vscode');
exports.activate = context => {
	const out = process.env.SECRET_PROBE_OUT;
	const report = value => fs.writeFileSync(out, JSON.stringify(value));
	context.subscriptions.push(
		vscode.commands.registerCommand('secretProbe.store', async () => {
			try { await context.secrets.store('probe', process.env.SECRET_PROBE_VALUE); report({stored: true}); }
			catch (error) { report({stored: false, error: String(error)}); }
		}),
		vscode.commands.registerCommand('secretProbe.read', async () => {
			try { report({value: await context.secrets.get('probe') ?? null}); }
			catch (error) { report({value: null, error: String(error)}); }
		}));
};
