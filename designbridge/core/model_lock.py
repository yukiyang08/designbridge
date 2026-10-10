"""Shared lock to serialize first-time heavy ML library loading across threads.

Startup warmup (``designbridge.core.warmup.run_startup_warmup``) runs in a
background daemon thread and does not block the server from accepting
requests. If a real request comes in while warmup is still loading models,
both threads may try to import/load ``transformers`` (or
``sentence-transformers`` / SAM 2) submodules for the first time at the same
moment. These libraries use custom lazy-attribute-resolution machinery
(e.g. transformers' ``_LazyModule.__getattr__``) that is not fully
thread-safe for concurrent first-time resolution from multiple threads, and
this has been observed to intermittently raise errors like
``cannot import name 'AutoImageProcessor' from 'transformers'``.

All lazy model-loading entry points (SAM 2 predictor, depth/segmentation
models, CLIP evaluator, text embedding models, ...) should acquire ``MODEL_LOAD_LOCK`` around their
first-time import + ``from_pretrained``/construction logic so that at most
one such heavy load can happen process-wide at any given moment.
"""

from __future__ import annotations

import threading

MODEL_LOAD_LOCK = threading.RLock()
