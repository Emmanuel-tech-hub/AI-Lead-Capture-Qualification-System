"""Generates starbiz-content-engine.json, the n8n workflow for the Starbiz video pipeline.

Run:  python3 build_workflow.py
Then import the JSON into n8n (Workflows -> Import from File).
"""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).with_name("starbiz-content-engine.json")


def nid():
    return str(uuid.uuid4())


nodes = []
connections = {}


def node(name, ntype, version, params, pos, **extra):
    n = {"parameters": params, "id": nid(), "name": name, "type": ntype,
         "typeVersion": version, "position": list(pos)}
    n.update(extra)
    nodes.append(n)
    return name


def link(src, dst, out=0):
    outs = connections.setdefault(src, {"main": []})["main"]
    while len(outs) <= out:
        outs.append([])
    outs[out].append({"node": dst, "type": "main", "index": 0})


CFG = "$('Config').first().json"

# ---------------------------------------------------------------- triggers + config
node("Manual Run (Test)", "n8n-nodes-base.manualTrigger", 1, {}, (0, 200))
node("Schedule: Mon/Wed/Fri 9am", "n8n-nodes-base.scheduleTrigger", 1.2, {
    "rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * 1,3,5"}]}
}, (0, 400))


def a(name, value, typ="string"):
    return {"id": nid(), "name": name, "value": value, "type": typ}


node("Config", "n8n-nodes-base.set", 3.4, {
    "assignments": {"assignments": [
        a("brandName", "Starbiz Cleaning LLC"),
        a("city", "Suwanee, GA"),
        a("website", "www.starbizcleaning.com"),
        a("phone", "(XXX) XXX-XXXX"),
        a("telegramChatId", "YOUR_TELEGRAM_CHAT_ID"),
        a("googleSheetId", "YOUR_GOOGLE_SHEET_ID"),
        a("claudeModel", "claude-opus-5-5"),
        a("videoSubmitUrl", "https://YOUR-VIDEO-PROVIDER/api/generate"),
        a("videoStatusUrlTemplate", "https://YOUR-VIDEO-PROVIDER/api/jobs/{id}"),
        a("videoModel", "kling-3.0"),
        a("aspectRatio", "9:16"),
        a("videoSeconds", 8, "number"),
        a("maxPollAttempts", 20, "number"),
        a("blotatoYoutubeAccountId", "YOUR_BLOTATO_YOUTUBE_ACCOUNT_ID"),
        a("youtubePrivacy", "public"),
        a("wordsToCheck", "cheap,guarantee,best in,#1,free,lowest price,100%,cure,kill all germs"),
    ]},
    "options": {},
}, (220, 300))
link("Manual Run (Test)", "Config")
link("Schedule: Mon/Wed/Fri 9am", "Config")

# ---------------------------------------------------------------- 1. idea
node("Get Topic Ideas", "n8n-nodes-base.googleSheets", 4.5, {
    "operation": "read",
    "documentId": {"__rl": True, "mode": "id", "value": "={{ " + CFG + ".googleSheetId }}"},
    "sheetName": {"__rl": True, "mode": "name", "value": "Topics"},
    "filtersUI": {"values": [{"lookupColumn": "Status", "lookupValue": "New"}]},
    "options": {},
}, (440, 300), alwaysOutputData=True)
link("Config", "Get Topic Ideas")

PICK_TOPIC = r"""// Picks the first "New" topic from the sheet. Falls back to a built-in list if the sheet is empty.
const cfg = $('Config').first().json;
const rows = $input.all().map(i => i.json).filter(r => r && String(r.Topic || '').trim());

const fallback = [
  'How often should you deep clean your kitchen?',
  '3 bathroom cleaning mistakes most people make',
  'What a move-out clean includes (and why it saves your deposit)',
  'Why offices that get cleaned regularly have fewer sick days',
  'The 10-minute daily reset that keeps your home tidy',
  'What to expect from your first professional house cleaning',
];

if (rows.length) {
  const r = rows[0];
  return [{ json: { topic: String(r.Topic).trim(), notes: r.Notes || '', rowNumber: r.row_number ?? null, fromSheet: true, cfg } }];
}
const pick = fallback[Math.floor(Math.random() * fallback.length)];
return [{ json: { topic: pick, notes: '', rowNumber: null, fromSheet: false, cfg } }];
"""
node("Pick Topic", "n8n-nodes-base.code", 2, {"jsCode": PICK_TOPIC}, (660, 300))
link("Get Topic Ideas", "Pick Topic")

# ---------------------------------------------------------------- 2. script (Claude)
SYSTEM_PROMPT = (
    "You write short-form video content for ${$json.cfg.brandName}, a family-owned residential and "
    "commercial cleaning company in ${$json.cfg.city}. Audience: busy homeowners, renters and local "
    "office managers. Tone: warm, helpful, confident, never pushy. Rules: no prices, no guarantees, no "
    "health or medical claims, never claim results you cannot show, never describe fake before/after "
    "results, no competitor names. The video clip is AI-generated, so the visual prompt must describe a "
    "realistic, clean, bright scene with no on-screen text, no logos and no recognizable real people."
)

CLAUDE_BODY = """={{ JSON.stringify({
  model: $json.cfg.claudeModel,
  max_tokens: 4000,
  fallbacks: 'default',
  output_config: {
    effort: 'medium',
    format: {
      type: 'json_schema',
      schema: {
        type: 'object',
        additionalProperties: false,
        required: ['title', 'description', 'hashtags', 'videoPrompt', 'hook'],
        properties: {
          title: { type: 'string', description: 'YouTube Shorts title, max 90 characters, no clickbait' },
          hook: { type: 'string', description: 'First spoken/visual line, max 12 words' },
          description: { type: 'string', description: '3-6 short lines: the tip, then a call to action with website and phone' },
          hashtags: { type: 'array', items: { type: 'string' }, description: '5-8 hashtags without the # symbol' },
          videoPrompt: { type: 'string', description: 'Detailed prompt for an AI video model: one ' + $json.cfg.videoSeconds + '-second vertical shot, camera movement, lighting, setting' }
        }
      }
    }
  },
  system: `""" + SYSTEM_PROMPT + """`,
  messages: [{
    role: 'user',
    content: 'Create one YouTube Short about this topic: ' + $json.topic +
      ($json.notes ? '\\nExtra notes: ' + $json.notes : '') +
      '\\nCall to action details - website: ' + $json.cfg.website + ', phone: ' + $json.cfg.phone + '.'
  }]
}) }}"""

node("Write Script (Claude)", "n8n-nodes-base.httpRequest", 4.2, {
    "method": "POST",
    "url": "https://api.anthropic.com/v1/messages",
    "authentication": "genericCredentialType",
    "genericAuthType": "httpHeaderAuth",
    "sendHeaders": True,
    "headerParameters": {"parameters": [
        {"name": "anthropic-version", "value": "2023-06-01"},
        {"name": "anthropic-beta", "value": "server-side-fallback-2026-07-01"},
    ]},
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": CLAUDE_BODY,
    "options": {"timeout": 120000},
}, (880, 300))
link("Pick Topic", "Write Script (Claude)")

PARSE_SCRIPT = r"""// Reads Claude's structured JSON answer and prepares everything the review step needs.
const res = $input.first().json;
const prev = $('Pick Topic').first().json;
const cfg = prev.cfg;

if (res.stop_reason === 'refusal') {
  throw new Error('Claude declined this topic: ' + prev.topic + '. Pick a different topic in the sheet.');
}
const textBlock = (res.content || []).find(b => b.type === 'text');
if (!textBlock) throw new Error('No text in Claude response: ' + JSON.stringify(res).slice(0, 500));
const s = JSON.parse(textBlock.text);

const tags = (s.hashtags || []).map(t => '#' + String(t).replace(/^#/, '').replace(/\s+/g, '')).join(' ');
const title = String(s.title).slice(0, 100);
const description = (s.description.trim() + '\n\n' + tags).slice(0, 4900);

// Flag words you asked to double-check before anything is posted.
const words = String(cfg.wordsToCheck || '').split(',').map(w => w.trim()).filter(Boolean);
const haystack = (title + ' ' + description).toLowerCase();
const flagged = words.filter(w => haystack.includes(w.toLowerCase()));

const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

return [{ json: {
  topic: prev.topic, rowNumber: prev.rowNumber, cfg,
  title, description, hook: s.hook, videoPrompt: s.videoPrompt,
  flagged,
  titleHtml: esc(title), descriptionHtml: esc(description),
}}];
"""
node("Parse Script", "n8n-nodes-base.code", 2, {"jsCode": PARSE_SCRIPT}, (1100, 300))
link("Write Script (Claude)", "Parse Script")

# ---------------------------------------------------------------- 3. video (Higgsfield or any async video API)
VIDEO_BODY = """={{ JSON.stringify({
  model: $json.cfg.videoModel,
  prompt: $json.videoPrompt,
  aspect_ratio: $json.cfg.aspectRatio,
  duration: $json.cfg.videoSeconds
}) }}"""
node("Start Video (Higgsfield)", "n8n-nodes-base.httpRequest", 4.2, {
    "method": "POST",
    "url": "={{ $json.cfg.videoSubmitUrl }}",
    "authentication": "genericCredentialType",
    "genericAuthType": "httpHeaderAuth",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": VIDEO_BODY,
    "options": {"timeout": 60000},
}, (1320, 300))
link("Parse Script", "Start Video (Higgsfield)")

SAVE_JOB = r"""// Remembers the video job ID so we can check on it.
const r = $input.first().json;
const id = r.id ?? r.job_id ?? r.request_id ?? r.task_id ?? r.data?.id ?? r.data?.job_id ?? r.generation_id;
if (!id && !r.status_url) throw new Error('Could not find a job id in the video API response: ' + JSON.stringify(r).slice(0, 500));
const s = $('Parse Script').first().json;
const statusUrl = r.status_url || s.cfg.videoStatusUrlTemplate.replace('{id}', id);
return [{ json: { ...s, jobId: id || null, statusUrl } }];
"""
node("Save Job ID", "n8n-nodes-base.code", 2, {"jsCode": SAVE_JOB}, (1540, 300))
link("Start Video (Higgsfield)", "Save Job ID")

node("Wait 60 Seconds", "n8n-nodes-base.wait", 1.1, {"amount": 60, "unit": "seconds"},
     (1760, 300), webhookId=nid())
link("Save Job ID", "Wait 60 Seconds")

node("Check Video Status", "n8n-nodes-base.httpRequest", 4.2, {
    "url": "={{ $('Save Job ID').first().json.statusUrl }}",
    "authentication": "genericCredentialType",
    "genericAuthType": "httpHeaderAuth",
    "options": {"timeout": 60000},
}, (1980, 300))
link("Wait 60 Seconds", "Check Video Status")

READ_STATUS = r"""// Works with most video APIs: finds the status word and the finished video URL wherever they are.
const r = $input.first().json;
const job = $('Save Job ID').first().json;

function findVideoUrl(obj, depth = 0) {
  if (!obj || depth > 6) return null;
  if (typeof obj === 'string') {
    return /^https?:\/\/\S+\.(mp4|mov|webm)(\?\S*)?$/i.test(obj) ? obj : null;
  }
  if (Array.isArray(obj)) { for (const v of obj) { const u = findVideoUrl(v, depth + 1); if (u) return u; } return null; }
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v === 'string' && /video|output|url/i.test(k) && /^https?:\/\//.test(v) && !/status|cancel|logs/i.test(k)) {
      if (/\.(mp4|mov|webm)/i.test(v) || /video/i.test(k)) return v;
    }
    const u = findVideoUrl(v, depth + 1); if (u) return u;
  }
  return null;
}

const status = String(r.status ?? r.state ?? r.data?.status ?? r.data?.state ?? '').toLowerCase();
const videoUrl = findVideoUrl(r);
const attempt = $runIndex + 1;
const max = Number(job.cfg.maxPollAttempts || 20);

let state = 'pending';
if (['failed', 'error', 'canceled', 'cancelled', 'nsfw', 'rejected'].includes(status)) state = 'failed';
else if (videoUrl && (['completed', 'succeeded', 'success', 'done', 'finished', 'ready', ''].includes(status) || !status)) state = 'ready';
else if (attempt >= max) state = 'failed';

return [{ json: { ...job, state, videoUrl, providerStatus: status || 'unknown', attempt,
  failReason: state === 'failed' ? (attempt >= max ? 'Timed out after ' + attempt + ' checks' : 'Provider status: ' + status) : null } }];
"""
node("Read Video Status", "n8n-nodes-base.code", 2, {"jsCode": READ_STATUS}, (2200, 300))
link("Check Video Status", "Read Video Status")


def if_params(left, value):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            "conditions": [{"id": nid(), "leftValue": left, "rightValue": value,
                            "operator": {"type": "string", "operation": "equals"}}],
            "combinator": "and",
        },
        "options": {},
    }


node("Video Ready?", "n8n-nodes-base.if", 2.2, if_params("={{ $json.state }}", "ready"), (2420, 300))
link("Read Video Status", "Video Ready?")
node("Video Failed?", "n8n-nodes-base.if", 2.2, if_params("={{ $json.state }}", "failed"), (2640, 460))
link("Video Ready?", "Video Failed?", out=1)
link("Video Failed?", "Wait 60 Seconds", out=1)

node("Alert: Video Failed", "n8n-nodes-base.telegram", 1.2, {
    "chatId": "={{ $json.cfg.telegramChatId }}",
    "text": "=⚠️ Starbiz video could not be made.\n\nTopic: {{ $json.topic }}\nReason: {{ $json.failReason }}\n\nNothing was posted. Check the video provider dashboard or try again.",
    "additionalFields": {"appendAttribution": False},
}, (2860, 460))
link("Video Failed?", "Alert: Video Failed", out=0)

# ---------------------------------------------------------------- 5. review in Telegram
node("Send Video Preview", "n8n-nodes-base.telegram", 1.2, {
    "operation": "sendVideo",
    "chatId": "={{ $json.cfg.telegramChatId }}",
    "file": "={{ $json.videoUrl }}",
    "additionalFields": {"caption": "=🎬 New Starbiz video ready for review\nTopic: {{ $json.topic }}"},
}, (2640, 140), onError="continueRegularOutput")
link("Video Ready?", "Send Video Preview", out=0)

COPY_TEXT = (
    "=📝 <b>Tap a box to copy it</b>\n\n"
    "<b>TITLE</b>\n<code>{{ $('Read Video Status').first().json.titleHtml }}</code>\n\n"
    "<b>DESCRIPTION</b>\n<pre>{{ $('Read Video Status').first().json.descriptionHtml }}</pre>\n\n"
    "{{ $('Read Video Status').first().json.flagged.length ? '⚠️ <b>Words to check:</b> ' + $('Read Video Status').first().json.flagged.join(', ') : '✅ No flagged words' }}\n\n"
    "🔗 <a href=\"{{ $('Read Video Status').first().json.videoUrl }}\">Open the video</a>"
)
node("Send Text to Copy", "n8n-nodes-base.telegram", 1.2, {
    "chatId": "={{ $('Read Video Status').first().json.cfg.telegramChatId }}",
    "text": COPY_TEXT,
    "additionalFields": {"appendAttribution": False, "parse_mode": "HTML", "disable_web_page_preview": True},
}, (2860, 140))
link("Send Video Preview", "Send Text to Copy")

node("Review & Edit (Telegram)", "n8n-nodes-base.telegram", 1.2, {
    "operation": "sendAndWait",
    "chatId": "={{ $('Read Video Status').first().json.cfg.telegramChatId }}",
    "message": "=👆 Watch the video and read the text above.\n\nTap the button to approve, edit, or reject.\nTo edit: copy the text above, fix it, and paste it into the form. Leave a box empty to keep the AI version.",
    "responseType": "customForm",
    "defineForm": "fields",
    "formFields": {"values": [
        {"fieldLabel": "Decision", "fieldType": "dropdown", "requiredField": True,
         "fieldOptions": {"values": [{"option": "Approve as is"}, {"option": "Approve with my edits"}, {"option": "Reject"}]}},
        {"fieldLabel": "New Title", "fieldType": "text", "placeholder": "Leave empty to keep the AI title (max 100 characters)"},
        {"fieldLabel": "New Description", "fieldType": "textarea", "placeholder": "Leave empty to keep the AI description"},
    ]},
    "options": {
        "messageButtonLabel": "Review & Edit",
        "responseFormTitle": "Starbiz Video Review",
        "responseFormDescription": "Approve, edit, or reject this video before it posts to YouTube.",
        "responseFormButtonLabel": "Submit",
        "limitWaitTime": {"values": {"limitType": "afterTimeInterval", "resumeAmount": 48, "resumeUnit": "hours"}},
    },
}, (3080, 140), webhookId=nid())
link("Send Text to Copy", "Review & Edit (Telegram)")

APPLY_EDITS = r"""// Uses your edits when you typed them, otherwise keeps the AI text.
const form = $input.first().json || {};
const d = form.data || form;
const pick = (label) => {
  const v = d[label] ?? d[label.toLowerCase()] ?? d[label.replace(/\s+/g, '_').toLowerCase()];
  return typeof v === 'string' ? v.trim() : '';
};
const v = $('Read Video Status').first().json;

let decision = pick('Decision') || 'No response';
const newTitle = pick('New Title');
const newDescription = pick('New Description');

const finalTitle = (newTitle || v.title).slice(0, 100);
const finalDescription = (newDescription || v.description).slice(0, 4900);
const approved = decision.startsWith('Approve');

return [{ json: { ...v, decision, approved: approved ? 'yes' : 'no', finalTitle, finalDescription,
  edited: Boolean(newTitle || newDescription) } }];
"""
node("Apply My Edits", "n8n-nodes-base.code", 2, {"jsCode": APPLY_EDITS}, (3300, 140))
link("Review & Edit (Telegram)", "Apply My Edits")

node("Approved?", "n8n-nodes-base.if", 2.2, if_params("={{ $json.approved }}", "yes"), (3520, 140))
link("Apply My Edits", "Approved?")

# ---------------------------------------------------------------- 6. post via Blotato
BLOTATO_BODY = """={{ JSON.stringify({
  post: {
    accountId: $json.cfg.blotatoYoutubeAccountId,
    content: {
      text: $json.finalDescription,
      mediaUrls: [$json.videoUrl],
      platform: 'youtube'
    },
    target: {
      targetType: 'youtube',
      title: $json.finalTitle,
      privacyStatus: $json.cfg.youtubePrivacy,
      shouldNotifySubscribers: true,
      containsSyntheticMedia: true
    }
  }
}) }}"""
node("Post to YouTube (Blotato)", "n8n-nodes-base.httpRequest", 4.2, {
    "method": "POST",
    "url": "https://backend.blotato.com/v2/posts",
    "authentication": "genericCredentialType",
    "genericAuthType": "httpHeaderAuth",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": BLOTATO_BODY,
    "options": {"timeout": 120000},
}, (3740, 40), onError="continueRegularOutput")
link("Approved?", "Post to YouTube (Blotato)", out=0)

POST_RESULT = r"""// Turns Blotato's answer into a simple result for the log and the Telegram message.
const r = $input.first().json;
const v = $('Apply My Edits').first().json;
const ok = !r.error && (r.postSubmissionId || r.id || r.success !== false);
return [{ json: { ...v, posted: ok ? 'Posted' : 'Post failed',
  blotatoId: r.postSubmissionId || r.id || '',
  blotatoMessage: r.error ? (r.error.message || JSON.stringify(r.error)) : (r.message || '') } }];
"""
node("Post Result", "n8n-nodes-base.code", 2, {"jsCode": POST_RESULT}, (3960, 40))
link("Post to YouTube (Blotato)", "Post Result")


def sheet_cols(values, match=None):
    return {
        "mappingMode": "defineBelow",
        "value": values,
        "matchingColumns": match or [],
        "schema": [{"id": k, "displayName": k, "required": False, "defaultMatch": False, "display": True,
                    "type": "string", "canBeUsedToMatch": True} for k in values],
    }


node("Mark Topic Used", "n8n-nodes-base.googleSheets", 4.5, {
    "operation": "update",
    "documentId": {"__rl": True, "mode": "id", "value": "={{ " + CFG + ".googleSheetId }}"},
    "sheetName": {"__rl": True, "mode": "name", "value": "Topics"},
    "columns": sheet_cols({"row_number": "={{ $json.rowNumber }}", "Status": "={{ $json.posted === 'Posted' ? 'Posted' : 'New' }}"}, ["row_number"]),
    "options": {},
}, (4180, 40), onError="continueRegularOutput")
link("Post Result", "Mark Topic Used")

LOG_COLS = {
    "Date": "={{ $now.toFormat('yyyy-MM-dd HH:mm') }}",
    "Topic": "={{ $('Apply My Edits').first().json.topic }}",
    "Title": "={{ $('Apply My Edits').first().json.finalTitle }}",
    "Decision": "={{ $('Apply My Edits').first().json.decision }}",
    "Edited": "={{ $('Apply My Edits').first().json.edited ? 'Yes' : 'No' }}",
    "Result": "={{ $('Post Result').isExecuted ? $('Post Result').first().json.posted : 'Not posted' }}",
    "Video URL": "={{ $('Apply My Edits').first().json.videoUrl }}",
    "Blotato ID": "={{ $('Post Result').isExecuted ? $('Post Result').first().json.blotatoId : '' }}",
}
node("Log Result", "n8n-nodes-base.googleSheets", 4.5, {
    "operation": "append",
    "documentId": {"__rl": True, "mode": "id", "value": "={{ " + CFG + ".googleSheetId }}"},
    "sheetName": {"__rl": True, "mode": "name", "value": "Log"},
    "columns": sheet_cols(LOG_COLS),
    "options": {},
}, (4400, 40), onError="continueRegularOutput")
link("Mark Topic Used", "Log Result")

node("Tell Me: Posted", "n8n-nodes-base.telegram", 1.2, {
    "chatId": "={{ $('Apply My Edits').first().json.cfg.telegramChatId }}",
    "text": "={{ $('Post Result').first().json.posted === 'Posted' ? '✅ Sent to YouTube via Blotato!' : '❌ Blotato could not post it.' }}\n\nTitle: {{ $('Apply My Edits').first().json.finalTitle }}\n{{ $('Post Result').first().json.blotatoMessage ? 'Details: ' + $('Post Result').first().json.blotatoMessage : 'Check the Blotato dashboard for the live link.' }}",
    "additionalFields": {"appendAttribution": False},
}, (4620, 40))
link("Log Result", "Tell Me: Posted")

node("Log Rejected", "n8n-nodes-base.googleSheets", 4.5, {
    "operation": "append",
    "documentId": {"__rl": True, "mode": "id", "value": "={{ " + CFG + ".googleSheetId }}"},
    "sheetName": {"__rl": True, "mode": "name", "value": "Log"},
    "columns": sheet_cols(LOG_COLS),
    "options": {},
}, (3740, 260), onError="continueRegularOutput")
link("Approved?", "Log Rejected", out=1)

node("Tell Me: Not Posted", "n8n-nodes-base.telegram", 1.2, {
    "chatId": "={{ $('Apply My Edits').first().json.cfg.telegramChatId }}",
    "text": "=🛑 Not posted ({{ $('Apply My Edits').first().json.decision }}).\nTopic: {{ $('Apply My Edits').first().json.topic }}\n\nThe topic stays \"New\" in the sheet, so it will be tried again next run. Change its Status to \"Skip\" if you never want it.",
    "additionalFields": {"appendAttribution": False},
}, (3960, 260))
link("Log Rejected", "Tell Me: Not Posted")

# ---------------------------------------------------------------- sticky notes (instructions inside n8n)


def sticky(text, pos, w, h, color):
    nodes.append({"parameters": {"content": text, "height": h, "width": w, "color": color},
                  "id": nid(), "name": f"Note {len(nodes)}", "type": "n8n-nodes-base.stickyNote",
                  "typeVersion": 1, "position": list(pos)})


sticky("## 1-2. IDEA + SCRIPT\nReads a \"New\" topic from the **Topics** sheet, then Claude writes the title, description, hashtags and video prompt.\n\n**Set up:** fill in the **Config** node. Anthropic credential = Header Auth, name `x-api-key`.",
       (380, 0), 880, 240, 5)
sticky("## 3. VIDEO\nSends the prompt to your video provider and checks every 60 seconds until it's ready.\n\n**Only part to adjust:** check Higgsfield's API docs and update `videoSubmitUrl`, `videoStatusUrlTemplate` and the body in **Start Video** if their field names differ.",
       (1280, 0), 1300, 240, 3)
sticky("## 5. YOU APPROVE (TELEGRAM)\nYou get the video, the text in tap-to-copy boxes, flagged words, and a **Review & Edit** button: Approve / Approve with my edits / Reject.",
       (2600, -150), 900, 200, 4)
sticky("## 6. POST (BLOTATO)\nPosts to YouTube with your final title and description, marks the topic used, logs everything, and tells you on Telegram.\nBlotato credential = Header Auth, name `blotato-api-key`.",
       (3700, -150), 1100, 180, 6)

workflow = {
    "name": "Starbiz Content Engine (YouTube via Blotato)",
    "nodes": nodes,
    "connections": connections,
    "active": False,
    "settings": {"executionOrder": "v1", "timezone": "America/New_York"},
    "pinData": {},
    "tags": [],
}
OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n")
print(f"Wrote {OUT} with {len(nodes)} nodes")
