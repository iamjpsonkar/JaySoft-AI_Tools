"""jsat._improve — self-improvement signal capture.

JSAT records friction it hits in ITSELF (crashes, capability gaps, UX friction,
performance regressions) so `jsat improve` can later diagnose it and propose a
patch to JSAT's own source.

Privacy contract: capture is local-file-only and JSAT-internal-only. Nothing about
the indexed codebase is recorded — see ``_sanitize`` — and nothing leaves the
machine unless a human runs ``jsat improve --report``. Disable with
``JSAT_NO_IMPROVE=1``, ``privacy.no_telemetry: true``, or ``improve.enabled: false``.
"""
from __future__ import annotations

from jsat._improve._capture import flush, record_signal, set_mode, suppress_nudge
from jsat._improve._store import bundles_dir, improve_dir, read_clusters, read_state

__all__ = [
    "bundles_dir",
    "flush",
    "improve_dir",
    "read_clusters",
    "read_state",
    "record_signal",
    "set_mode",
    "suppress_nudge",
]
