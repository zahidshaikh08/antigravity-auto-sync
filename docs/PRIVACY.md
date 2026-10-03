# Privacy Policy for Antigravity Sync

**Last Updated:** October 3, 2026

**Antigravity Sync** ("we", "our", or "the application") is an open-source tool and IDE extension designed to synchronize Google Antigravity chat history across your personal devices. 

We are committed to absolute data privacy and transparency. This Privacy Policy explains how our application interacts with your Google account and local data.

---

## 1. Zero-Knowledge Architecture

Antigravity Sync operates on a **zero-knowledge, client-to-cloud architecture**:
- **No Third-Party Servers**: We do not operate any backend servers, databases, or intermediary proxies.
- **Direct Communication**: All communication happens directly between your local machine (Antigravity IDE) and Google's official Drive API (`https://www.googleapis.com`).
- **Zero Telemetry / Zero Tracking**: The application does not collect analytics, telemetry, or user activity logs.

---

## 2. Google OAuth & Google Drive API Access

When you connect your Google Account, the application requests the following restricted permission:

- **Scope**: `https://www.googleapis.com/auth/drive.file`
- **What this allows**: View and manage Google Drive files and folders that you have opened or created with this app.
- **What this DOES NOT allow**:
  - The application **cannot** read, access, search, or view your personal documents, Google Docs, photos, spreadsheets, or any other files stored on your Google Drive.
  - Access is sandboxed strictly to the `AntigravitySync/` folder created by this application.

### Use of Google User Data
Any data retrieved or stored through Google Drive APIs is used solely to synchronize your Antigravity conversation archives between your own authorized machines. We never share, transfer, or sell your Google user data to third parties, advertising platforms, data brokers, or AI model trainers.

---

## 3. Local Data Storage & Security

- **Authentication Tokens**: OAuth access and refresh tokens are stored locally on your machine at `~/.gemini/config/gdrive_auth.json` with standard operating system user permissions.
- **Token Transmission**: Tokens are sent exclusively to Google's token endpoint (`https://oauth2.googleapis.com/token`) over HTTPS.
- **Disconnection**: Running `Logout` in the extension or CLI immediately deletes your local authentication tokens.

---

## 4. Data Retention & Deletion

- **You Own Your Data**: All synchronized chats reside inside your personal Google Drive account in the `AntigravitySync` folder.
- **Full Control**: You can delete any individual chat or the entire backup directory directly from your Google Drive at any time.
- **Revoking Access**: You can revoke the application's access at any time via your Google Account Security settings at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

---

## 5. Contact & Support

If you have questions regarding this Privacy Policy or the security of Antigravity Sync, please contact:

- **Developer**: Zahid Shaikh
- **Email**: `shaikhzahid333@gmail.com` / `shaikhzahid9013@gmail.com`
- **GitHub Repository**: [https://github.com/zahidshaikh08/antigravity-auto-sync](https://github.com/zahidshaikh08/antigravity-auto-sync)
