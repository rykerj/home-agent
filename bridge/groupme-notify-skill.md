---
name: groupme-notify
description: Send a spontaneous or scheduled alert message to the user on GroupMe via the local bridge endpoint.
category: notifications
---

# GroupMe Outbound Notification

The in-container Hermes agent talks to the outside world over **GroupMe**. A
local HTTP bridge (Python) exposes a single outbound-only endpoint that cron
jobs, background monitors, subagents, and any long-running task can use to push
a message back to you.

## Send a message

When something needs to reach the user — an alert, a deal, a monitor result —
send it by running this curl command via the terminal tool:

    curl -s -X POST http://127.0.0.1:8443/notify \
         -H 'Content-Type: application/json' \
         -d '{"text": "YOUR MESSAGE HERE"}'

Notes:
- Loopback-only: the bridge returns **403** for any non-local caller, so only
  run this from inside this container's own tooling (never expose it).
- Body must be JSON with a single `text` key. A missing/empty/unparseable body
  yields **400**.
- GroupMe caps messages at ~1000 chars and the bridge truncates at 950; keep the
  payload tight or split it into shorter, sequential calls.

## Formatting for readability
- Put alert-worthy content (the headline fact, numbers, link) first.
- Avoid huge markdown tables or box-drawing blocks; plain sentences render as
  clean chat bubbles.
- Strip ANSI codes and thinking-block wrappers before sending — the bridge does
  not strip them, and they will surface in your GroupMe feed verbatim.

## When to use it
- A scheduled cron job or background monitor fires a threshold alert.
- A background task finishes work worth surfacing to you.
- Anything that would otherwise just sit unread in the agent's log.

If there is nothing genuinely noteworthy, stay silent — do not post filler.
