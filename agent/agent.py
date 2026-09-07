"""
USA Business Setup & Onboarding Agent — reference implementation.

A minimal, dependency-light agent loop over any OpenAI-compatible chat
completions API. The compliance boundaries from agent/system-prompt.md are
enforced here IN CODE, not just in the prompt:

  * data-pack validation before any research or form work
  * hard block on sensitive fields (SSN/ITIN, ID images, credentials, OTPs)
  * prefill stops at identity-verification / attestation sections
  * PII redaction on everything that gets logged or echoed back

Setup:
    pip install httpx
    export LLM_API_BASE="https://api.openai.com/v1"   # or any compatible base
    export LLM_API_KEY="sk-..."
    export LLM_MODEL="gpt-4o-mini"                    # or glm-4.6, etc.
    python agent.py --profile profiles/sample-profile.json

Replace the tool stubs with live integrations (web research, your form
pipeline, browser automation) — the loop and guardrails stay the same.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import httpx

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT = (HERE / "system-prompt.md").read_text(encoding="utf-8")

MAX_STEPS = 12          # hard cap on model <-> tool round-trips
REQUEST_TIMEOUT = 120.0

# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

FORBIDDEN_KEYS = {
    "ssn", "ssn_number", "social_security_number", "itin",
    "personal_id_number", "id_photo", "id_document", "passport_image",
    "selfie", "bank_password", "password", "otp", "2fa_code",
    "verification_code",
}

SSN_LIKE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
ID_LIKE = re.compile(r"\b\d{2}-\d{7}\b")            # EIN-shaped IDs also redacted
CODE_LIKE = re.compile(r"\b(?:otp|code)\s*[:=]\s*\w+", re.IGNORECASE)

ATTESTATION_MARKERS = (
    "i certify", "i agree to the", "electronic signature", "e-signature",
    "terms of service", "beneficial owner certification",
    "identity verification", "know your customer", "kyc",
    "upload your id", "photo id", "selfie", "video verification",
)


def redact(text: str) -> str:
    """PII-safe redaction for logs, echoes and persisted output."""
    text = SSN_LIKE.sub("[REDACTED]", text)
    text = ID_LIKE.sub("[REDACTED-ID]", text)
    text = CODE_LIKE.sub("[REDACTED-CODE]", text)
    return text


def guard_tool_args(name: str, args: dict) -> dict:
    """Refuse any tool call that tries to move sensitive data around."""
    for key in args:
        if str(key).lower() in FORBIDDEN_KEYS:
            raise PermissionError(
                f"Blocked: tool '{name}' received forbidden field '{key}'. "
                "Identity data and credentials are client-only."
            )
    return args


def looks_like_attestation(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in ATTESTATION_MARKERS)


# ---------------------------------------------------------------------------
# Tools (local logic where safe; stubs where a live integration belongs)
# ---------------------------------------------------------------------------

REQUIRED_TOP = ["business", "industry", "owners", "contact", "consents"]
REQUIRED_BUSINESS = [
    "legalName", "entityType", "stateOfFormation", "ein", "businessAddress",
]

HIGH_RISK_KEYWORDS = {
    "cbd", "cannabis", "nutraceutical", "supplement", "adult", "gaming",
    "gambling", "casino", "crypto", "forex", "dropshipping", "travel",
    "telemarketing", "debt collection", "credit repair", "firearms",
    "vape", "tobacco", "escort",
}


def tool_validate_data_pack(profile: dict) -> dict:
    """Step 0 gate: nothing else runs until the pack is valid."""
    missing_top = [k for k in REQUIRED_TOP if k not in profile]
    business = profile.get("business") or {}
    missing_business = [k for k in REQUIRED_BUSINESS if k not in business]
    owners = profile.get("owners") or []
    owners_ok = bool(owners) and all(
        {"fullName", "ownershipPct", "residency"} <= set(o) for o in owners
    )
    consented = bool(profile.get("consents", {}).get("dataUseAuthorized"))
    blob = json.dumps(profile).lower()
    contraband = sorted(k for k in FORBIDDEN_KEYS if f'"{k}"' in blob)
    valid = not missing_top and not missing_business and owners_ok and consented and not contraband
    return {
        "valid": valid,
        "missingTopLevel": missing_top,
        "missingBusinessFields": missing_business,
        "ownersComplete": owners_ok,
        "clientConsent": consented,
        "forbiddenFieldsFound": contraband,
        "note": "Do not start any sign-up until valid == true. Request missing items from the client.",
    }


def tool_classify_risk(profile: dict) -> dict:
    """Step 1: honest risk classification with expectation setting."""
    industry = profile.get("industry") or {}
    text = " ".join(
        [str(industry.get("description", ""))]
        + [str(k) for k in industry.get("nicheKeywords", [])]
    ).lower()
    hits = sorted(k for k in HIGH_RISK_KEYWORDS if k in text)
    risk_class = "high" if hits else ("low" if industry.get("website") else "medium")
    expectations = {
        "high": "Fewer mainstream options; expect reserves, longer underwriting, higher fees. Never promise approval.",
        "medium": "Mainstream options possible; verify prohibited-business lists before recommending.",
        "low": "Full mainstream shortlist available; still verify current requirements.",
    }[risk_class]
    return {"riskClass": risk_class, "flaggedKeywords": hits, "expectations": expectations}


def tool_research_banking_options(
    niche: str, risk_class: str, monthly_volume_usd: float = 0
) -> dict:
    """Step 2: candidate shortlist. In production, wire this to live web
    research and re-verify every row against CURRENT official docs."""
    banks = [
        {"name": "Mercury", "notes": "Startup-friendly; check current non-resident signer policy.",
         "verify": "https://mercury.com"},
        {"name": "Relay", "notes": "Multiple envelopes; good cash management.",
         "verify": "https://relay.fi"},
        {"name": "Novo", "notes": "Simple digital banking; historically requires a US-person signer — confirm before recommending.",
         "verify": "https://novo.co"},
        {"name": "Chase Business Complete Checking", "notes": "Branch network; in-person KYC may suit the client.",
         "verify": "https://www.chase.com/business"},
    ]
    processors = [
        {"name": "Stripe", "notes": "Strong APIs; restricted-business list applies.",
         "verify": "https://stripe.com/legal/restricted-businesses"},
        {"name": "Square", "notes": "Fast start for retail and mobile; check the high-risk list.",
         "verify": "https://squareup.com/legal/restricted-businesses"},
        {"name": "Shopify Payments", "notes": "Best inside Shopify storefronts; not standalone.",
         "verify": "https://www.shopify.com/legal"},
        {"name": "Authorize.net", "notes": "Established gateway; pairs with a merchant account.",
         "verify": "https://www.authorize.net"},
    ]
    return {
        "shortlist": {"banks": banks, "processors": processors},
        "filtersApplied": {
            "niche": niche,
            "riskClass": risk_class,
            "monthlyVolumeUsd": monthly_volume_usd,
        },
        "mandatoryNextStep": (
            "Re-verify each candidate's signer-eligibility and prohibited-business "
            "list against current official docs; record the date checked. Drop any "
            "provider the client's signer profile cannot onboard with."
        ),
    }


def tool_prefill_signup(provider: str, profile: dict) -> dict:
    """Step 3: map the pack onto a generic US business application.
    Production: replace with a per-provider mapping + your form pipeline."""
    b = profile.get("business", {})
    prefill = {
        "section1_business_information": {
            "legalName": b.get("legalName"),
            "dba": b.get("dba"),
            "entityType": b.get("entityType"),
            "stateOfFormation": b.get("stateOfFormation"),
            "address": b.get("businessAddress"),
            "website": b.get("website"),
            "businessPhone": profile.get("contact", {}).get("businessPhone"),
            "businessEmail": profile.get("contact", {}).get("businessEmail"),
        },
        "section2_ownership": {
            "owners": [
                {
                    "fullName": o.get("fullName"),
                    "ownershipPct": o.get("ownershipPct"),
                    "residency": o.get("residency"),
                }
                for o in profile.get("owners", [])
            ],
            "note": "Names and percentages only. SSNs/ITINs and ID documents are entered by the client directly in the provider portal.",
        },
        "section3_industry_and_volume": {
            "description": profile.get("industry", {}).get("description"),
            "expectedMonthlyVolumeUsd": profile.get("industry", {}).get("expectedMonthlyVolumeUsd"),
            "averageTicketUsd": profile.get("industry", {}).get("averageTicketUsd"),
        },
    }
    return {
        "provider": provider,
        "prefill": prefill,
        "completedThroughSection": 3,
        "stop": {
            "stoppedAt": "section4_identity_verification",
            "reason": "KYC boundary: identity verification and attestations are completed by the client only.",
        },
        "handoverRequired": True,
    }


def tool_generate_handover_note(provider: str, login_url: str = "") -> str:
    """Step 4: the client-facing KYC handover note."""
    return "\n".join([
        f"✅ {provider}: form details completed up to Section 3 "
        "(business, ownership, industry & volume).",
        "",
        "What you need to do now (10–15 minutes):",
        "1. Log in here: " + (login_url or "[provider application link]"),
        "2. Complete Section 4 — identity verification: upload your photo ID "
        "and finish the selfie/video check.",
        "3. Review and sign any certification boxes yourself (Section 5).",
        "",
        "Have ready: government photo ID, proof of address if requested.",
        "⚠️ For security, never share SSN/ITIN, ID photos, or verification "
        "codes in this chat — enter them only inside the official portal.",
    ])


def tool_website_checklist(physical_products: bool = True) -> dict:
    """Step 5: merchant-approval website checklist."""
    items = [
        {"item": "Home page with a clear value proposition",
         "status": "template ready (website-template/index.html)"},
        {"item": "About page with a real business story",
         "status": "template ready — replace tokens"},
        {"item": "Products / Services page with clear pricing",
         "status": "template ready — replace tokens"},
        {"item": "Contact page matching the business address and phone",
         "status": "template ready — must match application data"},
        {"item": "Privacy Policy (real, not placeholder)",
         "status": "template ready — counsel review advised"},
        {"item": "Terms of Service",
         "status": "template ready — counsel review advised"},
        {"item": "Refund / Return Policy",
         "status": "template ready — processors require it"},
        {"item": "Shipping & Delivery Policy",
         "status": "template ready" if physical_products
                  else "not required (no physical goods)"},
        {"item": "SSL (https) live on the domain",
         "status": "client / host action"},
        {"item": "No lorem-ipsum or placeholder content anywhere",
         "status": "verify before merchant review"},
    ]
    return {
        "checklist": items,
        "note": "Merchant reviewers commonly reject sites with missing policies "
                "or contact details that do not match the application.",
    }


TOOL_IMPL: dict[str, Callable[..., Any]] = {
    "validate_data_pack": tool_validate_data_pack,
    "classify_risk": tool_classify_risk,
    "research_banking_options": tool_research_banking_options,
    "prefill_signup": tool_prefill_signup,
    "generate_handover_note": tool_generate_handover_note,
    "website_checklist": tool_website_checklist,
}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "validate_data_pack",
        "description": "Validate the client data pack before any research or form work. Run this first.",
        "parameters": {"type": "object", "properties": {
            "profile": {"type": "object", "description": "The full client data pack JSON"},
        }, "required": ["profile"]}}},
    {"type": "function", "function": {
        "name": "classify_risk",
        "description": "Classify the business niche into low/medium/high risk with expectation notes.",
        "parameters": {"type": "object", "properties": {
            "profile": {"type": "object"},
        }, "required": ["profile"]}}},
    {"type": "function", "function": {
        "name": "research_banking_options",
        "description": "Shortlist candidate business banks and merchant processors for the client.",
        "parameters": {"type": "object", "properties": {
            "niche": {"type": "string"},
            "risk_class": {"type": "string", "enum": ["low", "medium", "high"]},
            "monthly_volume_usd": {"type": "number"},
        }, "required": ["niche", "risk_class"]}}},
    {"type": "function", "function": {
        "name": "prefill_signup",
        "description": "Map the validated data pack onto a provider application. Stops at identity verification / attestation sections.",
        "parameters": {"type": "object", "properties": {
            "provider": {"type": "string"},
            "profile": {"type": "object"},
        }, "required": ["provider", "profile"]}}},
    {"type": "function", "function": {
        "name": "generate_handover_note",
        "description": "Generate the client handover note for KYC completion.",
        "parameters": {"type": "object", "properties": {
            "provider": {"type": "string"},
            "login_url": {"type": "string"},
        }, "required": ["provider"]}}},
    {"type": "function", "function": {
        "name": "website_checklist",
        "description": "Merchant-approval website checklist for the client's site.",
        "parameters": {"type": "object", "properties": {
            "physical_products": {"type": "boolean"},
        }, "required": []}}},
]

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


def run_agent(profile: dict, api_base: str, api_key: str, model: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "Client data pack attached. Run the full workflow: validate the "
            "pack, classify risk, research suitable banks and processors, "
            "then prefill the best-fit application and stop with a KYC "
            "handover note.\n\n"
            "CLIENT DATA PACK (JSON):\n" + json.dumps(profile, indent=2)
        )},
    ]
    headers = {"Authorization": f"Bearer {api_key}"}

    for _ in range(MAX_STEPS):
        resp = httpx.post(
            f"{api_base}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages, "tools": TOOL_SPECS},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]

        if msg.get("tool_calls"):
            messages.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": msg["tool_calls"],
            })
            for call in msg["tool_calls"]:
                name = call["function"]["name"]
                try:
                    raw = json.loads(call["function"].get("arguments") or "{}")
                    args = guard_tool_args(name, raw)
                    impl = TOOL_IMPL.get(name)
                    if impl is None:
                        payload = json.dumps({"error": f"unknown tool: {name}"})
                    else:
                        payload = json.dumps(impl(**args), indent=2, default=str)
                except (PermissionError, ValueError) as exc:
                    payload = json.dumps({"blocked": True, "reason": str(exc)})
                except Exception as exc:  # report, don't crash the loop
                    payload = json.dumps({"error": redact(str(exc))})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": redact(payload),
                })
            continue

        final = msg.get("content") or ""
        # Belt and braces: if the model drifts into attestation/KYC territory,
        # force a re-issue as a client handover note.
        if looks_like_attestation(final) and "handover" not in final.lower():
            messages.append({"role": "user", "content": (
                "Your reply appears to include attestation or identity-"
                "verification actions. You may not perform those. Re-issue "
                "the message as a client handover note instead."
            )})
            continue
        return final

    return ("Step limit reached. Issue a status summary now: what is done, "
            "what is pending, and the client's next action.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="USA Business Onboarding Agent (reference implementation)"
    )
    parser.add_argument("--profile", required=True,
                        help="Path to a client data pack JSON")
    args = parser.parse_args()

    api_base = os.environ.get("LLM_API_BASE", "").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    if not (api_base and api_key):
        print("Set LLM_API_BASE and LLM_API_KEY first. See the file header.",
              file=sys.stderr)
        return 2

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    print("== USA Onboarding Agent ==")
    print("PII redaction: ON | Attestation boundary: ON | KYC handover: ON\n")

    final = run_agent(profile, api_base, api_key, model)
    print(redact(final))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
