# reeln-plugin-google

A [reeln-cli](https://github.com/StreamnDad/reeln-cli) plugin for Google platform integration — YouTube livestreams, uploads, playlists, and comments.

## Install

```bash
pip install reeln-plugin-google
```

Or for development:

```bash
git clone https://github.com/StreamnDad/reeln-plugin-google
cd reeln-plugin-google
make dev-install
```

## Google Cloud Setup

Before using this plugin, you need a Google Cloud project with OAuth credentials. Follow these steps exactly.

### 1. Create a GCP Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown (top-left) → **New Project**
3. Name it (e.g., `reeln-livestream`) and click **Create**
4. Select the new project from the dropdown

### 2. Enable the YouTube Data API v3

1. Go to **APIs & Services → Library**
2. Search for **YouTube Data API v3**
3. Click it and press **Enable**

### 3. Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Select **External** user type → **Create**
3. Fill in:
   - **App name** — anything (e.g., `reeln`)
   - **User support email** — your Gmail
   - **Developer contact email** — your Gmail
4. Click **Save and Continue**
5. On the **Scopes** page, click **Add or Remove Scopes** and add:
   - `https://www.googleapis.com/auth/youtube`
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube.force-ssl`
6. Click **Update** → **Save and Continue**
7. On the **Test users** page, click **Add Users** and enter your Google email address
8. Click **Save and Continue** → **Back to Dashboard**

> **Testing vs Production mode:**
> Your app starts in "Testing" mode with these limitations:
> - Only the test users you added can authorize
> - OAuth tokens expire every **7 days** (you'll need to re-authorize)
> - Maximum 100 test users
>
> Once your setup is stable, you can publish to "Production" mode to remove token expiry and the user cap. Production apps requesting sensitive scopes require Google verification, but apps for personal use with limited users typically pass quickly.

### 4. Create OAuth 2.0 Client ID

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name it (e.g., `reeln-desktop`) and click **Create**
5. Click **Download JSON** (the download icon)

### 5. Protect the Secrets File

The downloaded `client_secrets.json` contains your OAuth client ID and client secret. Treat it like a password.

```bash
# Move it somewhere safe outside your repo
mv ~/Downloads/client_secret_*.json ~/.config/reeln/client_secrets.json

# Restrict permissions (macOS/Linux)
chmod 600 ~/.config/reeln/client_secrets.json
```

**Never commit this file to git.** It allows anyone to impersonate your application and request access to YouTube accounts.

## Plugin Configuration

Add the Google plugin to your reeln config. **All capabilities are off by default** — enable only what you need:

```json
{
  "plugins": {
    "enabled": ["google"],
    "settings": {
      "google": {
        "client_secrets_file": "~/.config/reeln/client_secrets.json",
        "create_livestream": true,
        "manage_playlists": true,
        "upload_highlights": true,
        "upload_shorts": false,
        "privacy_status": "unlisted"
      }
    }
  }
}
```

### Feature Flags

Every capability must be explicitly enabled. Nothing runs unless you set the flag to `true`.

| Flag | Default | What it does |
|------|---------|--------------|
| `create_livestream` | `false` | Create a YouTube broadcast on `reeln game init` and write the URL to shared context |
| `manage_playlists` | `false` | Create a per-game playlist on `reeln game init`; auto-add uploads when combined with `upload_highlights` |
| `upload_highlights` | `false` | Upload the merged highlights video after `reeln highlights merge` |
| `upload_shorts` | `false` | Upload Shorts after `reeln render short` (detected via `filter_complex`) |

### Other Options

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `client_secrets_file` | Yes | — | Path to GCP OAuth client secrets JSON |
| `credentials_cache` | No | `<data_dir>/google/oauth.json` | OAuth credentials cache path |
| `privacy_status` | No | `unlisted` | Video/livestream privacy: `public`, `unlisted`, or `private` |
| `category_id` | No | `20` | YouTube category ID (`20` = Gaming) |
| `tags` | No | `[]` | Default video tags |
| `scopes` | No | `[youtube, youtube.upload, youtube.force-ssl]` | OAuth scopes |

## First Run

On the first `reeln game init`, the plugin opens a browser for OAuth consent:

1. Sign in with the Google account you added as a test user
2. Click **Continue** (past the "unverified app" warning)
3. Grant the requested YouTube permissions
4. The browser shows "The authentication flow has completed" — you can close it

Credentials are cached at `~/Library/Application Support/reeln/data/google/oauth.json` (macOS) or `~/.local/share/reeln/data/google/oauth.json` (Linux). The file is automatically `chmod 600`'d. Tokens auto-refresh on subsequent runs — you won't see the browser again unless tokens expire or you re-authenticate.

## Troubleshooting

**"Access blocked" or "Error 403: access_denied"**
You didn't add your Google email as a test user. Go to **OAuth consent screen → Test users** and add it.

**"Quota exceeded"**
The YouTube Data API has a daily quota (default 10,000 units). Creating a livestream costs ~1,600 units. If you're hitting limits, check your [quota dashboard](https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas).

**Token expired after 7 days**
This happens in Testing mode. Either re-run to trigger the browser flow again, or publish your OAuth consent screen to Production mode (see [Testing vs Production](#3-configure-the-oauth-consent-screen) above).

**"redirect_uri_mismatch"**
Your OAuth client type isn't set to **Desktop app**. Delete the credential and create a new one with the correct type.

## How It Works

The plugin hooks into reeln-cli lifecycle events. Here's the typical game-day flow:

```
reeln game init
  └─ ON_GAME_INIT
       ├─ create_livestream → YouTube broadcast bound to your OBS stream key
       └─ manage_playlists  → per-game playlist (livestream auto-added if both enabled)

reeln highlights merge
  └─ ON_HIGHLIGHTS_MERGED
       └─ upload_highlights → upload merged video; auto-add to playlist if enabled

reeln render short
  └─ POST_RENDER (for each short)
       └─ upload_shorts → upload as YouTube Short (#Shorts appended to title)

reeln game finish
  └─ ON_GAME_FINISH → reset cached state for next game
```

### Shared Context

The plugin writes results to `context.shared` so sibling plugins (e.g., a Discord notifier) can consume them:

| Key | Value |
|-----|-------|
| `shared["livestreams"]["google"]` | Livestream URL (`https://youtube.com/live/...`) |
| `shared["playlists"]["google"]` | Playlist ID |
| `shared["uploads"]["google"]["video_id"]` | Uploaded highlights video ID |
| `shared["uploads"]["google"]["url"]` | Uploaded highlights URL |
| `shared["uploads"]["google"]["shorts"]` | List of `{"video_id", "url"}` for each Short |

### LLM Metadata

If an LLM plugin writes metadata to `shared["uploads"]["google"]` before the upload hooks fire, the plugin uses it instead of auto-generating from game info:

| Key | Used by |
|-----|---------|
| `title` | Highlights upload |
| `description` | Highlights upload |
| `tags` | Highlights and Shorts upload |
| `short_title` | Shorts upload |
| `short_description` | Shorts upload |

## Development

```bash
make dev-install    # uv venv + editable install with dev deps
make test           # pytest with 100% coverage
make lint           # ruff check
make format         # ruff format
make check          # lint + mypy + test
```

## License

AGPL-3.0-only
