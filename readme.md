# USA Business Onboarding — Agent Kit + iPhone App

Production-ready kit for onboarding USA-based businesses: AI agent core
(banking/processor research, sign-up prefill with hard KYC handover,
merchant-ready website setup) **plus** the companion **iPhone Agent PWA**
(Roman Urdu UI, hybrid online/offline brain, WhatsApp handover pings).

## Repository map

| Path | What it is |
|---|---|
| `agent/system-prompt.md` | Refined agent system prompt (v2) — paste into any LLM platform |
| `agent/agent.py` | Reference implementation — OpenAI-compatible tool loop, guardrails enforced in code |
| `agent/client-profile.schema.json` | Client data pack schema (SSN/ITIN marked never-collect) |
| `profiles/sample-profile.json` | Fictional sample data pack |
| `workflows/n8n-usa-onboarding-agent.json` | Importable n8n workflow: intake → guardrail → agent → KYC handover |
| `website-template/` | Merchant-approval website kit (8 pages incl. refund & shipping policies) |
| `index.html` + `V2 iPhone Agent-Interactive Prototype.html` | The iPhone web app (PWA entry) |
| `V2 iPhone Agent-Infinite Canvas.html` | Full design delivery canvas (intro / design system / screens) |
| `manifest.webmanifest` + `sw.js` + `icons/` | PWA install + offline cache layer |
| `iPhone Agent User Guide.pdf` / `.html` | Mukammal Roman Urdu user guide |

## The compliance model

1. **KYC stop** — the agent never completes identity verification; it produces a
   handover note with the exact resume point and client steps.
2. **No attestation** — certification boxes, ToS acceptance, e-sign and final
   submit are always the client's action.
3. **Never-collect data** — SSN/ITIN, ID photos, selfies, passwords and OTPs are
   refused at schema level, blocked in tool args, redacted in logs.
4. **No guarantees** — approvals are never promised; high-risk niches get early,
   honest expectation setting.
5. **Freshness** — provider requirements are re-verified against current official
   sources, with the check date recorded.

## Quickstart

**Prompt-only:** paste `agent/system-prompt.md` into any LLM platform.

**Python reference agent:**
```bash
pip install httpx
export LLM_API_BASE="https://api.openai.com/v1"
export LLM_API_KEY="***"
export LLM_MODEL="gpt-4o-mini"
python agent/agent.py --profile profiles/sample-profile.json
```

**iPhone app (GitHub Pages):**
1. Settings → Pages → Source: *Deploy from a branch* → `main` / `(root)` → Save
2. Open the Pages URL in iPhone Safari → Share → *Add to Home Screen*
3. First open online to cache; afterwards the workflow, checklists and handover
   generator work fully offline.

**n8n:** import `workflows/n8n-usa-onboarding-agent.json`, attach chat-model +
Gmail credentials, activate the webhook.

## Before production

- Replace the tool stubs in `agent/agent.py` with live integrations.
- Have counsel review `website-template/` policy pages; replace every `[token]`.
- Never commit real client data packs.
