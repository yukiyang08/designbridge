# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

DesignBridge is an interior-design AI workflow: a LangGraph pipeline behind a FastAPI backend, with a Vue 3 wizard frontend. Fuller specs live in `docs/DesignBridge.md` and `docs/SCHEMAS.md`; operational scripts (scraping, Supabase upload, quality filter) are in `docs/commands.md`.

## Commands

Run from the repo root (Windows; `PYTHONUTF8=1` is required in `.env` or emoji `print`s crash).

```bash
pip install -r requirements.txt
cd frontend && npm install

# backend — --reload-exclude is mandatory: artifacts/ is written on every generation
# and would otherwise restart the process mid-run and drop loaded models
uvicorn api:app --reload --reload-exclude "*/artifacts/*" --host 0.0.0.0 --port 8000

cd frontend && npm run dev        # frontend (Vite, :5173); also `npm run build`
start.bat                         # both of the above in two windows (README says start_app.bat; the file is start.bat)

python -m pytest test/ -q                                   # all tests
python -m pytest test/test_fengshui_constraints.py -q       # one file
python -m pytest test/test_x.py::test_name -q               # one test
```

No linter/formatter is configured. `.env` needs `GEMINI_API_KEY`, `FAL_KEY`, `HF_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (see README for what each is for).

## Architecture

**Request path:** Vue wizard → `api.py` (mounts `routers/{floorplan,generate,history,style}.py`, serves `artifacts/`, `style_kb/images`, `debug-console/`) → LangGraph in `designbridge/core/graph.py`. A background thread preloads ML models at startup (`core/warmup.py`).

**Graph** (`designbridge/core/graph.py`, nodes in `core/nodes/`, state in `core/state.py`):

```
requirement_analyzer → visual_preprocessing ─┬─ design   → layout_and_style_agent → composer ─┐
                                              └─ adjust   → adjuster_agent ───────────────────┤
                       clip_evaluator ← renderer ←────────────────────────────────┘
```

- Routing (new design vs. local edit) is decided entirely inside `requirement_analyzer`; there is no separate director node any more.
- `composer` only follows the layout path; inpaint edits (`adjuster_agent`) skip it.
- Quotation is deliberately **not** in the graph (30–40 s, doesn't affect the image); it is a separate `POST /api/quotation` the user triggers.

**Layout system** (`designbridge/layout/`) is the largest subsystem:
- `layout_agent.py` — `run_layout_agent`: LLM proposes placements → loop of hard constraints, geometric optimizer, soft-constraint scoring (stops at score ≥ 0.65 or `LAYOUT_MAX_ITER`) → projects the result to a ControlNet depth map. Falls back to `_default_layout` if the LLM fails.
- Split modules: `layout_items` (vocabulary, `FurnitureItem`), `layout_enforce` (geometry, scoring, enforcers), `floorplan_parse` (Gemini floor-plan/room detection), `floorplan_render` (pycairo floor-plan PNG), `projected_depth` (scene graph → depth/seg files).
- Two parallel constraint registries load `SKILL.md` frontmatter: `skills/layout-constraints/*` (always-on hard rules, enforcers in `layout_enforce._LAYOUT_ENFORCERS`) and `skills/constraints/*` (feng-shui rules, `special_constraints.py`, which has paired `_enforce_*`/`_verify_*`).
- Two depth projectors exist: `scene_graph_to_depth.py` (main path, via `projected_depth`) and `layout_projection.py` (older fallback used in `renderer.py` only when no depth file exists).
- Photo path: `vision.py` (Depth Anything V2 + UPerNet) → `depth_to_layout.py` / `photo_geometry.py` anchor the layout to the uploaded photo's floor plane.

**Rendering** (`designbridge/render/`, `core/nodes/renderer.py`): backend is chosen by a waterfall of `if backend == "placeholder"` checks (fal.ai FLUX img2img / depth+edge ControlNet, HF Kontext, Imagen, local SDXL). Almost every behaviour is gated by an env-backed flag in `designbridge/core/config.py` — check there before assuming a code path is live. Style swap reuses the previous render's `seed` (stored in `render_result.generation_params`) and, by default, drops the post-estimated depth (`STYLE_SWAP_DEPTH_LOCK`).

**Data:** Supabase (style vector search via bge-m3 text embeddings, storage) plus `designbridge/furniture_kb/ikea_embeddings.npz` (CLIP, IKEA matching). `style_kb/` is the offline pipeline that scrapes, captions, quality-filters and uploads style images; `export_dataset.py` + `train_style_lora.py` train style LoRAs.

**Frontend** (`frontend/src`): linear wizard `/` → `/start` → `/studio` (direct `/studio` without a draft redirects to `/start`). All wizard state lives in `composables/useDesignFlow.js` composed from `composables/design-flow/*.js`; steps are in `components/steps/`. `/room-plan` is an independent CAD tool unrelated to the wizard.

## Writing conventions

- Code comments and commit messages: concise, in Traditional Chinese. The codebase has many sprawling multi-paragraph comments (e.g. in `core/config.py`) — don't imitate them; one or two lines stating the non-obvious *why* is enough.
- Commit subject keeps the conventional prefix (`feat(scope):`, `fix:`, `refactor:`, `chore:`) followed by a short Chinese summary; add a body only when the reason isn't obvious from the diff.

## Gotchas

- Source files are CRLF; keep line endings when editing/moving code.
- `ablation_tests/` is git-ignored (local only); `localtor2.py` and `service-account.json` are ignored because they hold credentials.
- Tests live in `test/` (plus `requirement_tests/`, `scripts/test_*`); many hit real APIs or need local models, so expect some to be environment-dependent.
