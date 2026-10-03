const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

let statusBarItem;
let daemonProcess = null;
let outputChannel;

/**
 * Resolves the path to the bundled cli.py
 */
function getCliPath(context) {
    const extCli = path.join(context.extensionPath, 'cli.py');
    if (fs.existsSync(extCli)) {
        return extCli;
    }
    // Fallback to parent project workspace
    const workspaceCli = path.join(context.extensionPath, '..', 'cli.py');
    if (fs.existsSync(workspaceCli)) {
        return workspaceCli;
    }
    return extCli;
}

/**
 * Checks if user is authenticated with Google Drive
 */
function isAuthenticated() {
    const authFile = path.join(os.homedir(), '.gemini', 'config', 'gdrive_auth.json');
    if (!fs.existsSync(authFile)) {
        return false;
    }
    try {
        const raw = fs.readFileSync(authFile, 'utf8');
        const data = JSON.parse(raw);
        return Boolean(data.access_token || data.refresh_token);
    } catch {
        return false;
    }
}

/**
 * Updates the status bar appearance
 */
function updateStatusBar(status, details) {
    if (!statusBarItem) return;

    switch (status) {
        case 'not_connected':
            statusBarItem.text = '$(cloud) AGY Sync: Connect Drive';
            statusBarItem.tooltip = 'Google Drive is not connected. Click to set up auto-sync.';
            statusBarItem.backgroundColor = undefined;
            break;
        case 'active':
            statusBarItem.text = '$(cloud) AGY Sync: Active';
            statusBarItem.tooltip = 'Antigravity Auto-Sync is active. Watching for chat changes.';
            statusBarItem.backgroundColor = undefined;
            break;
        case 'syncing':
            statusBarItem.text = '$(sync~spin) AGY Syncing...';
            statusBarItem.tooltip = details || 'Synchronizing conversations with Google Drive...';
            break;
        case 'synced':
            statusBarItem.text = '$(cloud) AGY Sync: Synced';
            statusBarItem.tooltip = details || 'All conversations are up-to-date with Google Drive.';
            statusBarItem.backgroundColor = undefined;
            break;
        case 'error':
            statusBarItem.text = '$(cloud-offline) AGY Sync: Error';
            statusBarItem.tooltip = details || 'Sync encountered an error. Click for details.';
            statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
            break;
        case 'paused':
            statusBarItem.text = '$(cloud) AGY Sync: Paused';
            statusBarItem.tooltip = 'Background auto-sync is currently paused.';
            statusBarItem.backgroundColor = undefined;
            break;
    }
    statusBarItem.show();
}

/**
 * Starts the Python background daemon process
 */
function startDaemon(context) {
    stopDaemon();

    const config = vscode.workspace.getConfiguration('antigravitySync');
    if (!config.get('autoSync', true)) {
        updateStatusBar('paused');
        return;
    }

    if (!isAuthenticated()) {
        updateStatusBar('not_connected');
        return;
    }

    const pythonBin = config.get('pythonPath', 'python3');
    const cliPath = getCliPath(context);
    const interval = config.get('intervalSeconds', 30);

    outputChannel.appendLine(`[*] Starting sync daemon using: ${pythonBin} ${cliPath}`);
    updateStatusBar('active');

    try {
        daemonProcess = spawn(pythonBin, [cliPath, 'daemon', '--interval', String(interval)], {
            cwd: path.dirname(cliPath),
            env: { ...process.env, PYTHONUNBUFFERED: '1' }
        });

        daemonProcess.stdout.on('data', (chunk) => {
            const str = chunk.toString();
            outputChannel.append(str);

            if (str.includes('Detected local chat changes')) {
                updateStatusBar('syncing', 'Detected chat updates. Uploading to Google Drive...');
            } else if (str.includes('✔ Synced')) {
                updateStatusBar('synced', str.trim());
                if (config.get('showNotifications', true)) {
                    // Check if non-zero uploads or downloads
                    const match = str.match(/Uploaded:\s*(\d+),\s*Downloaded:\s*(\d+)/);
                    if (match && (parseInt(match[1]) > 0 || parseInt(match[2]) > 0)) {
                        vscode.window.showInformationMessage(
                            `Antigravity Sync: Uploaded ${match[1]}, Downloaded ${match[2]} conversation(s).`
                        );
                    }
                }
            } else if (str.includes('[!] Sync error')) {
                updateStatusBar('error', 'Sync error occurred. Click for details.');
            }
        });

        daemonProcess.stderr.on('data', (chunk) => {
            const errStr = chunk.toString();
            outputChannel.append(`[STDERR] ${errStr}`);
            if (errStr.includes('[!]') || errStr.includes('Error')) {
                updateStatusBar('error', errStr.trim().split('\n')[0]);
            }
        });

        daemonProcess.on('exit', (code) => {
            outputChannel.appendLine(`[*] Daemon exited with code: ${code}`);
            daemonProcess = null;
            if (code !== 0 && code !== null) {
                updateStatusBar('error', `Daemon stopped unexpectedly (code: ${code})`);
            }
        });
    } catch (err) {
        outputChannel.appendLine(`[!] Failed to spawn daemon: ${err.message}`);
        updateStatusBar('error', err.message);
    }
}

/**
 * Stops the background daemon process
 */
function stopDaemon() {
    if (daemonProcess) {
        try {
            daemonProcess.kill('SIGTERM');
        } catch {
            // ignore
        }
        daemonProcess = null;
        outputChannel.appendLine('[*] Daemon process stopped.');
    }
}

/**
 * Executes a one-time sync cycle
 */
async function runSyncNow(context) {
    if (!isAuthenticated()) {
        const choice = await vscode.window.showWarningMessage(
            'Google Drive is not connected yet.',
            'Connect Google Drive'
        );
        if (choice === 'Connect Google Drive') {
            vscode.commands.executeCommand('antigravitySync.login');
        }
        return;
    }

    const config = vscode.workspace.getConfiguration('antigravitySync');
    const pythonBin = config.get('pythonPath', 'python3');
    const cliPath = getCliPath(context);

    updateStatusBar('syncing', 'Manual sync in progress...');
    outputChannel.show(true);
    outputChannel.appendLine('\n================ [ MANUAL SYNC ] ================');

    return vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'Antigravity History Sync',
        cancellable: false
    }, (progress) => {
        return new Promise((resolve) => {
            progress.report({ message: 'Syncing with Google Drive...' });

            const proc = spawn(pythonBin, [cliPath, 'sync'], {
                cwd: path.dirname(cliPath),
                env: { ...process.env, PYTHONUNBUFFERED: '1' }
            });

            let outBuffer = '';
            let errBuffer = '';

            proc.stdout.on('data', (d) => {
                const text = d.toString();
                outBuffer += text;
                outputChannel.append(text);
            });

            proc.stderr.on('data', (d) => {
                const text = d.toString();
                errBuffer += text;
                outputChannel.append(`[ERR] ${text}`);
            });

            proc.on('close', (code) => {
                if (code === 0 && !outBuffer.includes('[!] Sync error')) {
                    updateStatusBar('synced');
                    vscode.window.showInformationMessage('✔ Antigravity Sync: All conversations successfully synced with Google Drive!');
                } else {
                    updateStatusBar('error');
                    vscode.window.showErrorMessage(`Antigravity Sync Error: ${errBuffer || 'Check Output panel for details.'}`);
                }
                resolve();
            });
        });
    });
}

/**
 * Initiates the Google Drive OAuth login
 */
async function runLogin(context) {
    const config = vscode.workspace.getConfiguration('antigravitySync');
    const pythonBin = config.get('pythonPath', 'python3');
    const cliPath = getCliPath(context);

    const terminal = vscode.window.createTerminal('Antigravity Sync Login');
    terminal.show();
    terminal.sendText(`${pythonBin} "${cliPath}" login`);

    vscode.window.showInformationMessage(
        'Browser opening for Google Drive authorization. Sign in and grant access to complete setup.',
        'View Instructions'
    ).then((sel) => {
        if (sel === 'View Instructions') {
            outputChannel.show();
        }
    });

    // Check periodically for token file creation to update status bar
    const checkInterval = setInterval(() => {
        if (isAuthenticated()) {
            clearInterval(checkInterval);
            updateStatusBar('active');
            vscode.window.showInformationMessage('✔ Google Drive successfully connected! Background auto-sync is now active.');
            startDaemon(context);
        }
    }, 2000);

    setTimeout(() => clearInterval(checkInterval), 180000); // Stop checking after 3 minutes
}

/**
 * Disconnects Google Drive
 */
async function runLogout(context) {
    const confirm = await vscode.window.showWarningMessage(
        'Are you sure you want to disconnect Google Drive from Antigravity on this machine?',
        { modal: true },
        'Disconnect'
    );

    if (confirm !== 'Disconnect') return;

    stopDaemon();

    const config = vscode.workspace.getConfiguration('antigravitySync');
    const pythonBin = config.get('pythonPath', 'python3');
    const cliPath = getCliPath(context);

    const proc = spawn(pythonBin, [cliPath, 'logout'], { cwd: path.dirname(cliPath) });
    proc.on('close', () => {
        updateStatusBar('not_connected');
        vscode.window.showInformationMessage('✔ Disconnected from Google Drive.');
    });
}

/**
 * Shows interactive Status Menu QuickPick
 */
async function showStatusMenu(context) {
    const connected = isAuthenticated();
    const config = vscode.workspace.getConfiguration('antigravitySync');
    const autoSync = config.get('autoSync', true);

    const items = [];

    if (connected) {
        items.push({
            label: '$(sync) Sync Now',
            description: 'Run immediate two-way synchronization',
            action: 'syncNow'
        });
        items.push({
            label: autoSync ? '$(primitive-square) Pause Auto-Sync' : '$(play) Resume Auto-Sync',
            description: autoSync ? 'Currently active (watching chat changes)' : 'Currently paused',
            action: 'toggleAutoSync'
        });
        items.push({
            label: '$(list-unordered) View Local Conversations & Stats',
            description: 'Inspect indexed chats and storage footprint',
            action: 'viewStats'
        });
        items.push({
            label: '$(output) View Sync Logs',
            description: 'Show live background sync output',
            action: 'showLogs'
        });
        items.push({
            label: '$(sign-out) Disconnect Google Drive',
            description: 'Unlink your Google account on this machine',
            action: 'logout'
        });
    } else {
        items.push({
            label: '$(link) Connect Google Drive',
            description: 'Link your Google account with 1 click',
            action: 'login'
        });
        items.push({
            label: '$(list-unordered) View Local Conversations & Stats',
            description: 'Inspect local chats',
            action: 'viewStats'
        });
        items.push({
            label: '$(output) View Sync Logs',
            description: 'Show live background sync output',
            action: 'showLogs'
        });
    }

    const selection = await vscode.window.showQuickPick(items, {
        placeHolder: `Antigravity Cloud Auto-Sync (${connected ? 'Connected' : 'Not Connected'})`
    });

    if (!selection) return;

    switch (selection.action) {
        case 'syncNow':
            await runSyncNow(context);
            break;
        case 'toggleAutoSync':
            await config.update('autoSync', !autoSync, vscode.ConfigurationTarget.Global);
            if (!autoSync) {
                startDaemon(context);
                vscode.window.showInformationMessage('✔ Antigravity Auto-Sync resumed.');
            } else {
                stopDaemon();
                updateStatusBar('paused');
                vscode.window.showInformationMessage('Antigravity Auto-Sync paused.');
            }
            break;
        case 'viewStats':
            vscode.commands.executeCommand('antigravitySync.viewStats');
            break;
        case 'showLogs':
            outputChannel.show(true);
            break;
        case 'login':
            await runLogin(context);
            break;
        case 'logout':
            await runLogout(context);
            break;
    }
}

/**
 * Views conversation statistics
 */
function showStats() {
    const cacheFile = path.join(os.homedir(), '.gemini', 'antigravity-history', 'cache.json');
    if (!fs.existsSync(cacheFile)) {
        vscode.window.showInformationMessage('No Antigravity conversation cache found yet.');
        return;
    }

    try {
        const raw = fs.readFileSync(cacheFile, 'utf8');
        const data = JSON.parse(raw);
        const convs = Object.entries(data.conversations || {}).map(([id, meta]) => ({
            id,
            ...meta
        }));

        const totalSteps = convs.reduce((acc, c) => acc + (c.stepCount || 0), 0);

        const items = convs.map((c) => ({
            label: c.summary || c.id.slice(0, 8),
            description: `${c.stepCount || 0} steps`,
            detail: `Last modified: ${(c.lastModifiedTime || '').replace('T', ' ').slice(0, 19)}`
        }));

        vscode.window.showQuickPick(items, {
            placeHolder: `Total Local Conversations: ${convs.length} | Total Agent Steps: ${totalSteps}`
        });
    } catch (err) {
        vscode.window.showErrorMessage(`Failed to read conversation cache: ${err.message}`);
    }
}

/**
 * Extension activation
 */
function activate(context) {
    outputChannel = vscode.window.createOutputChannel('Antigravity Sync');
    outputChannel.appendLine('[*] Antigravity History Sync extension activated.');

    // Create status bar item
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = 'antigravitySync.statusMenu';
    context.subscriptions.push(statusBarItem);

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('antigravitySync.statusMenu', () => showStatusMenu(context)),
        vscode.commands.registerCommand('antigravitySync.syncNow', () => runSyncNow(context)),
        vscode.commands.registerCommand('antigravitySync.login', () => runLogin(context)),
        vscode.commands.registerCommand('antigravitySync.logout', () => runLogout(context)),
        vscode.commands.registerCommand('antigravitySync.toggleAutoSync', async () => {
            const config = vscode.workspace.getConfiguration('antigravitySync');
            const current = config.get('autoSync', true);
            await config.update('autoSync', !current, vscode.ConfigurationTarget.Global);
            if (!current) {
                startDaemon(context);
            } else {
                stopDaemon();
                updateStatusBar('paused');
            }
        }),
        vscode.commands.registerCommand('antigravitySync.viewStats', showStats)
    );

    // Initial state check
    if (isAuthenticated()) {
        updateStatusBar('active');
        startDaemon(context);
    } else {
        updateStatusBar('not_connected');
        vscode.window.showInformationMessage(
            'Antigravity Chat Auto-Sync: Connect your Google Drive to sync conversations across all your machines.',
            'Connect Google Drive',
            'Later'
        ).then((sel) => {
            if (sel === 'Connect Google Drive') {
                runLogin(context);
            }
        });
    }
}

/**
 * Extension deactivation
 */
function deactivate() {
    stopDaemon();
    if (outputChannel) {
        outputChannel.dispose();
    }
}

module.exports = {
    activate,
    deactivate
};
