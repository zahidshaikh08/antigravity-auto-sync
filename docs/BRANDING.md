# 🌌 Antigravity Sync — Brand Guidelines & Product Lexicon

Welcome to the brand identity, terminology, and design system specification for **Antigravity Sync**.

---

## 1. Brand Identity & Vision

- **Official Name**: **Antigravity Sync**
- **Short Name / CLI Handle**: `agy-sync`
- **Extension Identifier**: `zahidshaikh.antigravity-history-sync`
- **Primary Tagline**: 
  > *"Float your AI chats across every machine. Zero config. Zero friction."*
- **Secondary Tagline**:
  > *"Seamless cross-platform chat synchronization and backup for Google Antigravity."*
- **Brand Personality**: Futuristic, cosmic, aerospace-inspired, ultra-reliable, privacy-first.
- **Mission**: Free developers from machine lock-in by making Antigravity AI pair-programming state effortlessly ubiquitous across macOS, Windows, and Linux.

---

## 2. Official Visual Assets

| Asset | Path | Specs | Usage |
| :--- | :--- | :--- | :--- |
| **App Icon / Logo** | [`assets/logo.png`](../assets/logo.png) | 1024x1024 (256x256 packaged) | IDE extension icon, app icon, social avatar. |
| **Hero Banner** | [`assets/banner.png`](../assets/banner.png) | 1920x1080 (16:9) | GitHub README hero, social preview cards. |
| **Extension Icon** | [`extension/images/icon.png`](../extension/images/icon.png) | 256x256 PNG | Bundled within the `.vsix` extension package. |

---

## 3. Color Palette & Design Tokens

```
┌────────────────────────────────────────────────────────────────────────┐
│  Deep Space Dark        Neon Cyan Glow         Electric Violet         │
│  #0A0D14               #00F0FF                #7B2CBF                  │
│  (Canvas & Terminals)  (Active Sync & Orbit)  (Nebula Accents)         │
├────────────────────────────────────────────────────────────────────────┤
│  Cyber Sky Blue         Aurora Green           Starlight White         │
│  #38BDF8               #10B981                #F8FAFC                  │
│  (IDE Status Bar)      (Synced & Healthy)     (High-contrast Text)     │
└────────────────────────────────────────────────────────────────────────┘
```

- **Deep Space Black (`#0A0D14`)**: Background base evoking infinite space and antigravity physics.
- **Neon Cyan (`#00F0FF`)**: Primary accent representing levitation, energy fields, and data streams.
- **Electric Violet (`#7B2CBF`)**: Secondary accent representing AI intelligence and quantum cohesion.
- **Google Drive Blue (`#4285F4`)**: Connector accent for cloud authentication surfaces.
- **Aurora Green (`#10B981`)**: State accent for completed sync and healthy connections.

---

## 4. Product Terminology & Official Lexicon

When documenting features, explaining functionality, or communicating in UI prompts, use the following standardized terminology:

### 🗄️ The Warp Vault (`AntigravitySync/`)
- **Definition**: The private, sandboxed app directory located in your personal Google Drive account.
- **Key Guarantee**: Only your Antigravity instances can access it. Never accessible by third-party servers.

### 📦 Delta Capsule (`.agyzip`)
- **Definition**: The self-contained, portable conversation archive containing the SQLite database snapshot, turn-by-turn trajectory logs (`transcript.jsonl`), code plans, media attachments, and generated artifacts.
- **Key Guarantee**: 100% context retention—restoring a capsule reproduces the entire thought history of the AI pair programmer.

### 🛡️ The Safe-Merge Guarantee
- **Definition**: The non-destructive reconciliation algorithm that merges remote conversations without ever deleting or overwriting local chats.
- **Key Mechanism**: Automatic pre-merge snapshot creation saved to `~/.gemini/antigravity-history/backups/`.

### 🧭 Cross-Node Path Remapper
- **Definition**: The engine module that inspects workspace paths inside conversation states and automatically translates file URIs between operating systems (`file:///Users/...` ↔ `file:///C:/Users/...` ↔ `file:///home/...`).

### 👁️ Silent Sentinel (Background Daemon)
- **Definition**: The lightweight background watcher that monitors local Antigravity history for activity, waits for typing to pause (debounce), and executes atomic delta synchronizations without interrupting your coding flow.

---

## 5. Tone of Voice & Copy Guidelines

1. **Clear, Technical, Yet Effortless**:
   - *Do say*: *"Your chat history is synchronized with your private Google Drive vault."*
   - *Avoid*: *"We copied your databases to the cloud."*

2. **Empower User Ownership**:
   - *Do say*: *"Your personal Google Drive. Zero external servers. Complete privacy."*
   - *Avoid*: *"Cloud storage provided by us."*

3. **Frictionless Onboarding**:
   - *Do say*: *"1-click connection. Works silently in the background."*
   - *Avoid*: *"Requires setting up background services, cron jobs, and terminal daemons."*
