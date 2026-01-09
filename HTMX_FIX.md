# Fix for htmx WebSocket Extension Compatibility Issue

## Problem

The trivia app was experiencing the following error in the browser console:

```
ws.js:11 Uncaught TypeError: htmx.defineExtension is not a function
```

## Root Cause

The issue was caused by version incompatibility between htmx core and the htmx-ext-ws extension:

1. **FastHTML 0.4.0** loads scripts from unpkg.com without version pinning:
   - `https://unpkg.com/htmx.org@next/dist/htmx.min.js` - Uses `@next` tag which now resolves to htmx 2.x
   - `https://unpkg.com/htmx-ext-ws/ws.js` - Loads latest version which expects htmx 2.x API

2. **The Problem**: The htmx WebSocket extension's API changed between htmx 1.x and 2.x:
   - htmx 1.x uses `htmx.defineExtension()` to register extensions
   - htmx 2.x uses a different extension API
   - When unpkg serves mismatched versions, the extension fails to initialize

## Solution

Pin both htmx and the WebSocket extension to compatible versions:

```python
# Override htmx scripts with pinned versions compatible with FastHTML 0.4.0
# htmx 1.9.x is compatible with the older ws extension API
htmx_script = Script(src="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js")
# ws extension 1.x is compatible with htmx 1.x
htmx_ws_script = Script(src="https://unpkg.com/htmx-ext-ws@1.0.0/ws.js")

# Include these in the app initialization
app = FastHTML(hdrs=(htmx_script, htmx_ws_script, css, ThemeSwitch()), ws_hdr=False, htmx=False, on_startup=[app_startup])
```

Key changes:
- **htmx version**: Pinned to `1.9.12` (stable htmx 1.x release)
- **ws extension**: Pinned to `1.0.0` (compatible with htmx 1.x)
- **Disabled auto-loading**: Set `htmx=False` and `ws_hdr=False` to prevent FastHTML from loading the default (incompatible) versions

## Verification

To verify the fix is working:

1. Load the application in a browser
2. Open the browser's Developer Console (F12)
3. Check that there are no errors related to `htmx.defineExtension`
4. Verify that WebSocket functionality works (questions update in real-time)

## Why This Approach?

Per the agent instructions:
- Avoid upgrading FastHTML (would require significant code changes due to API changes)
- Pin dependencies to older, compatible versions instead
- Make minimal changes to fix the issue

## Future Considerations

If upgrading to FastHTML 2.x in the future:
- Will need to upgrade htmx to 2.x
- Will need to upgrade htmx-ext-ws to a 2.x compatible version
- May require code changes to adapt to new FastHTML API
