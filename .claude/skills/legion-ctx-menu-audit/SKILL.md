---
name: legion-ctx-menu-audit
description: Run the Legion right-click context-menu wiring audit against a live Legion instance and present a summary of which menu items are wired (create a process), not wired, pre-existing duplicates, or behavioural. Invoke when the user asks to audit/check/verify context menu actions, or runs "/legion-ctx-menu-audit".
argument-hint: [port] (default 8585)
---

# Legion Context Menu Wiring Audit

Audit every right-click menu item on every service row across all hosts in a running
Legion instance. Reports which items are wired (produce a process), not wired,
skipped due to a pre-existing duplicate, or behavioural (no process expected).

## Port

$ARGUMENTS — treat the argument as the port number. Default `8585` if omitted.

## Steps

### 1. Confirm the server is reachable

```bash
curl -s http://localhost:PORT/api/snapshot | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(f'hosts={len(d[\"hosts\"])} procs={len(d[\"processes\"])}')
"
```

If it fails, tell the user and stop.

### 2. Run the audit script

```bash
python3 -u /home/kali/Downloads/legion/scripts/legion_ctx_menu_audit.py --port PORT --out /tmp/legion_ctx_audit_results.json
```

**Note:** run as `kali` user (not sudo) — Firefox requires X11 access which root lacks.

The script:
- Launches a fresh Firefox via geckodriver (visible so the user can watch)
- For each host: left-panel Services table, then right-panel Services table
- For each row, opens the context menu and reads every button label
- Per button:
  - **Behavioural** (`Open in browser`, `Send to Brute`): noted, not clicked
  - **Pre-existing duplicate**: tool already ran on that host:port — records as `SKIP_DUP`
  - **Untested**: clicks the item, waits 3.5 s for a new process in `/api/snapshot`
    - New process → `WIRED`
    - No process but API probe confirms skip → `SKIP_DUP`
    - API probe creates process → `WIRED` (UI timing miss, route is functional)
    - Neither → `NOT_WIRED` (genuine wiring bug)
- Caches each label per panel so the same label is only fully tested once

### 3. Present the summary

```
Total menu items evaluated : N
  ✓ Wired                  : N
  ✗ NOT wired              : N
  ─ Pre-existing (dup skip): N   ← already ran; layer-1 dup check blocks re-run
  · Behavioural            : N   ← open-browser / send-to-brute, no process by design

NOT WIRED:
  ✗ [host] panel / row → 'label'
      <detail>
```

### 4. Explain categories

**SKIP_DUP** — not broken. Tool already ran on that host:port. The layer-1 duplicate
check (process-table lookup) prevents re-running the same tool on the same target.
To re-test a SKIP_DUP item: test it against a different host that has the same port/service.

**NOT_WIRED** — clicking the item produced no process AND the API probe confirms the
route cannot create one either. This is a genuine wiring bug.

**Known gap:** `Take screenshot` on the left-panel Services table always shows as
NOT_WIRED. This is an architectural gap — the left-panel `#services-body` contextmenu
handler only dispatches `port-action` types; the `take-screenshot` action type is only
handled in the right-panel `#host-detail-ports` handler. Right-panel Take screenshot
creates an Interactive eyewitness process correctly.

### 5. If new NOT_WIRED items appear (other than Take screenshot)

Investigate the dispatch chain:

```bash
# Get the action_index for the broken label
curl -s "http://localhost:PORT/api/menus/service?name=SERVICE_NAME" | \
  python3 -c "import sys,json; [print(i) for i in json.load(sys.stdin)['items'] if i.get('label')=='LABEL']"

# Call the endpoint directly
curl -s -X POST http://localhost:PORT/api/workspace/service-action \
  -H "Content-Type: application/json" \
  -d '{"targets":[["HOST_IP","PORT","tcp"]],"action_index":IDX}'
```

Common root causes:
- `{"reason":"skip"}` → duplicate check blocking
  - Layer-1: same tool already in process table for that host:port
  - Layer-2: NSE scripts stored for that port from a prior nmap scan.
    **Fix:** ensure `user_triggered=True` is passed to `checkDuplicate()` in
    `handleServiceNameAction()` in `controller/web_controller.py`
- `{"error":"Tool X not found"}` → tool_id mismatch between conf and portActions list
- No response / 500 → server-side exception; check `/api/logs`
- Menu item present but no XHR fires → JS handler missing for that `action.action`
  type in `#services-body` or `#host-detail-ports` contextmenu handler in `legion.js`

### 6. Full results

`/tmp/legion_ctx_audit_results.json` — full per-item breakdown with host, panel,
row, label, result, and detail for every evaluated item.

## Script location

`scripts/legion_ctx_menu_audit.py` — run directly for quick spot-checks:
```bash
python3 -u scripts/legion_ctx_menu_audit.py --port 8585
```

## Known wiring state (as of v10.145)

The layer-2 script-check bug in `checkDuplicate()` was fixed in v10.145 by passing
`user_triggered=True` from `handleServiceNameAction()`. Before this fix, any port
that had nmap NSE script results stored (i.e. every scanned port) would silently
skip all user-triggered tool actions. Affected tools included all `ftp-*.nse`,
`mysql-*.nse`, `ssh-default*`, and `rpcinfo`.

Expected clean-session audit result: `NOT_WIRED = 0` (only `Take screenshot` on left
panel remains, which is the known architectural gap).
