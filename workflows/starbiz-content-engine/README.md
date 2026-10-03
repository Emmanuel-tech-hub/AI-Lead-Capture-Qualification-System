# Starbiz Content Engine: n8n workflow

Turns cleaning tips into YouTube Shorts. **Nothing posts until you approve it on Telegram.**

```
Topics sheet → Claude writes script → AI video (Higgsfield) → Telegram review (edit / approve / reject) → Blotato posts to YouTube → Log
```

| File | What it is |
|---|---|
| `starbiz-content-engine.json` | **The workflow. Import this into n8n.** |
| `topics-template.csv` | 12 starter video topics for the Google Sheet |
| `build_workflow.py` | Script that generates the JSON. Edit it and re-run `python3 build_workflow.py` to change the workflow |

---

## What happens on Telegram (the approval step)

You get 3 messages:

1. **The video** to watch.
2. **The title and description** in tap-to-copy boxes, plus **⚠️ Words to check** if any word from your `wordsToCheck` list appears (for example "guarantee", "100%", "cheapest").
3. A **Review & Edit** button that opens a short form:
   - **Decision:** Approve as is / Approve with my edits / Reject
   - **New Title:** paste your rewritten title, or leave it empty to keep the AI version
   - **New Description:** paste your rewritten description, or leave it empty

**To edit:** tap the text box to copy it, fix the words, paste it into the form, and submit.

If you don't answer within **48 hours**, nothing is posted.

---

## Setup (about 30 minutes)

### 1. Import
n8n → **Workflows → Import from File** → choose `starbiz-content-engine.json`.

### 2. Google Sheet
Create a Google Sheet with two tabs:

- **Topics**: columns `Topic | Status | Notes`. Paste in `topics-template.csv`. Only rows with Status **New** are used.
- **Log**: columns `Date | Topic | Title | Decision | Edited | Result | Video URL | Blotato ID`

Copy the sheet ID from its URL (the long code between `/d/` and `/edit`).

### 3. Credentials (create in n8n, then select them in each node)

| Credential | n8n type | Header name | Value | Used by |
|---|---|---|---|---|
| Anthropic API Key | Header Auth | `x-api-key` | Key from console.anthropic.com | Write Script (Claude) |
| Video API Key | Header Auth | per provider docs (often `Authorization`, value `Bearer <key>`) | Higgsfield API key | Start Video, Check Video Status |
| Blotato API Key | Header Auth | `blotato-api-key` | Blotato → Settings → API | Post to YouTube (Blotato) |
| Telegram | Telegram API | n/a | Bot token from @BotFather | All Telegram nodes |
| Google Sheets | Google Sheets OAuth2 | n/a | Sign in with Google | Sheets nodes |

### 4. Fill in the **Config** node

| Field | What to put |
|---|---|
| `telegramChatId` | Your chat ID (message your bot, then use @userinfobot or check `getUpdates`) |
| `googleSheetId` | From step 2 |
| `blotatoYoutubeAccountId` | Blotato → connect YouTube → copy the account ID |
| `videoSubmitUrl`, `videoStatusUrlTemplate`, `videoModel` | From Higgsfield's API docs (see step 5) |
| `phone`, `website` | Starbiz contact details used in the call to action |
| `wordsToCheck` | Comma-separated words you want flagged before posting |
| `youtubePrivacy` | `public`, `unlisted`, or `private`. **Use `unlisted` for your first tests** |

### 5. ⚠️ The one part to check: the video API
Higgsfield's official MCP (`mcp.higgsfield.ai`) logs in through a browser, which suits chatting with Claude but not unattended automation. For n8n you need an **API key**.

1. Check whether your Higgsfield plan includes direct API access.
2. Update **Start Video (Higgsfield)** so the URL, field names (`model`, `prompt`, `aspect_ratio`, `duration`) and auth header match their docs.
3. Set `videoStatusUrlTemplate` to the endpoint that returns the job status. `{id}` is replaced with the job ID automatically.

The **Read Video Status** node already understands most providers' response shapes: it finds the status word and the finished `.mp4` URL wherever they are. If Higgsfield has no API on your plan, the same models (Kling, Veo) are available through **fal.ai** or **Replicate**. Change the two URLs and the credential, and nothing else needs to change.

### 6. Test
1. Set `youtubePrivacy` to `unlisted`.
2. Click **Manual Run (Test)**.
3. Approve on Telegram and check the video in YouTube Studio.
4. When you're happy, set it back to `public` and **activate** the workflow. It runs Mon/Wed/Fri at 9am Eastern; change this in the Schedule node.

---

## Good to know

- **Why Blotato:** YouTube locks uploads from new, unaudited apps to *private*. Blotato is already approved, and the same account can post to TikTok, Instagram and Facebook later.
- **AI disclosure:** posts are sent with `containsSyntheticMedia: true`, because YouTube requires AI-generated realistic content to be labeled.
- **Never use AI for "before and after" results.** Use real job photos for results; AI is for tips and explainers. The Claude instructions already forbid fake results, prices, guarantees and health claims.
- **Claude model:** `claude-opus-5-5`, with `fallbacks: "default"` enabled, so if a request is ever declined it is retried automatically on a fallback model. Change `claudeModel` in Config to use a different model.
- **Rejected topics** stay "New" and are retried next run. Set Status to `Skip` to retire one.
- **Adding TikTok later:** duplicate **Post to YouTube (Blotato)**, set `platform` and `targetType` to `tiktok`, use your Blotato TikTok account ID, and add the TikTok-specific target fields listed in Blotato's API docs (TikTok requires a few extra settings, such as privacy level).
