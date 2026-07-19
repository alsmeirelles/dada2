# Testing and Browser Support

## Automated gates

Every change must pass:

```bash
npm run lint
npm test
npm run build
```

Linting includes TypeScript, React hooks, Fast Refresh, and JSX accessibility
rules. Unit tests cover environment validation, directory ingestion, recovery
snapshots, annotation geometry, viewport transforms, real-time reconnection,
and shared UI behavior.

## Supported browsers

The supported desktop targets are the two most recent stable versions of
Google Chrome and Mozilla Firefox. Before a release, verify both browsers with
the same remote API deployment:

1. Login, token expiry, logout, and protected-route redirects.
2. Recursive directory selection, including nested paths and rejected files.
3. Interrupted/resumed uploads and offline recovery messaging.
4. Classification, boxes, polygons, zoom/pan, shortcuts, and autosave.
5. Two simultaneous annotators competing for the same queue item.
6. WebSocket disconnection, polling fallback, reconnect, and sequence gaps.
7. Iteration closure, training progress, ETA, failures, and statistics.
8. Keyboard-only navigation at 200% zoom with reduced motion enabled.

Firefox uses the directory-input fallback rather than relying on the File
System Access API. Both paths must produce the same relative manifest.

## Recovery tests

While editing, simulate offline mode or terminate the tab before autosave. On
reopening the same image in the same tab, the App should restore the 24-hour
session snapshot without overwriting a newer API version. No recovery snapshot
contains tokens, image bytes, or absolute local paths.
