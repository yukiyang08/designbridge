"""Depth map → 3D mesh GLB converter."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def depth_to_mesh_glb(
    rgb_image: Image.Image,
    depth_norm: np.ndarray,
    out_path: str,
    depth_scale: float = 0.9,
    edge_thresh: float = 0.2,
    mesh_w: int = 512,
    mesh_h: int = 384,
    side_wing: float = 0.35,
) -> str:
    """Convert depth + RGB into a flat-grid displacement GLB mesh with side walls.

    XY is a fixed rectangular grid (aspect-correct image plane).
    Z is depth displacement only.  Side-wall wings are added at the left/right
    edges to give a box-room feel when rotating.
    """
    import trimesh
    from scipy.ndimage import gaussian_filter

    aspect = mesh_w / mesh_h
    rgb = rgb_image.convert("RGB")

    # Resize depth to mesh resolution
    depth_pil = Image.fromarray((depth_norm * 255).astype(np.uint8))
    depth_small = np.array(
        depth_pil.resize((mesh_w, mesh_h), Image.BILINEAR), dtype=np.float32
    ) / 255.0

    # Global light blur to reduce depth estimation noise
    depth_blurred = gaussian_filter(depth_small, sigma=0.5).astype(np.float32)

    # Extra heavy blur blended into the bottom 35% to smooth foreground/floor tears
    depth_heavy = gaussian_filter(depth_small, sigma=8.0).astype(np.float32)
    blend_row = int(mesh_h * 0.65)
    alpha = np.zeros((mesh_h, 1), dtype=np.float32)
    alpha[blend_row:] = np.linspace(0, 1, mesh_h - blend_row)[:, np.newaxis]
    depth_small = (depth_blurred * (1 - alpha) + depth_heavy * alpha).astype(np.float32)

    u_grid, v_grid = np.meshgrid(
        np.arange(mesh_w, dtype=np.float32),
        np.arange(mesh_h, dtype=np.float32),
    )

    X = ((u_grid / (mesh_w - 1)) - 0.5) * aspect
    Y = -((v_grid / (mesh_h - 1)) - 0.5)
    Z = depth_small * depth_scale
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    uv = np.stack([
        u_grid.ravel() / (mesh_w - 1),
        1.0 - v_grid.ravel() / (mesh_h - 1),
    ], axis=1).astype(np.float32)

    d_flat = depth_small.ravel()
    faces: list[tuple[int, int, int]] = []
    for vi in range(mesh_h - 1):
        for ui in range(mesh_w - 1):
            i00 = vi * mesh_w + ui
            i01 = vi * mesh_w + (ui + 1)
            i10 = (vi + 1) * mesh_w + ui
            i11 = (vi + 1) * mesh_w + (ui + 1)
            depths = [d_flat[i00], d_flat[i01], d_flat[i10], d_flat[i11]]
            if max(depths) - min(depths) > edge_thresh:
                continue
            faces.append((i00, i10, i01))
            faces.append((i01, i10, i11))

    faces_arr = np.array(faces, dtype=np.int32)

    def _make_material():
        return trimesh.visual.texture.PBRMaterial(
            baseColorTexture=rgb,
            baseColorFactor=[1.0, 1.0, 1.0, 1.0],
            doubleSided=True,
        )

    mesh = trimesh.Trimesh(vertices=verts, faces=faces_arr, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=_make_material())

    scene_meshes: list[trimesh.Trimesh] = [mesh]

    # ── Box room walls + floor ────────────────────────────────────────────
    # Three perpendicular panels form an open box around the depth mesh:
    # left wall (X = -aspect/2, runs in Z), right wall (X = +aspect/2),
    # and floor (Y = -0.5, runs in X and Z).
    # UV for each panel stretches the outermost edge pixels of the image.
    if side_wing > 0:
        z_back  = -0.05               # slightly behind the mesh background
        z_front = depth_scale * 1.15  # slightly past the foreground
        s = 0.012                     # UV strip width (edge pixel fraction)

        panels = [
            # Left wall: at X = -aspect/2, extends toward viewer in Z
            dict(
                verts=np.array([
                    [-aspect/2, -0.5, z_back ],
                    [-aspect/2, -0.5, z_front],
                    [-aspect/2,  0.5, z_front],
                    [-aspect/2,  0.5, z_back ],
                ], dtype=np.float32),
                uv=np.array([
                    [s,   0.0], [0.0, 0.0],
                    [0.0, 1.0], [s,   1.0],
                ], dtype=np.float32),
            ),
            # Right wall: at X = +aspect/2
            dict(
                verts=np.array([
                    [aspect/2, -0.5, z_front],
                    [aspect/2, -0.5, z_back ],
                    [aspect/2,  0.5, z_back ],
                    [aspect/2,  0.5, z_front],
                ], dtype=np.float32),
                uv=np.array([
                    [1.0-s, 0.0], [1.0, 0.0],
                    [1.0,   1.0], [1.0-s, 1.0],
                ], dtype=np.float32),
            ),
            # Floor: at Y = -0.5, extends from back to front in Z
            dict(
                verts=np.array([
                    [-aspect/2, -0.5, z_front],
                    [ aspect/2, -0.5, z_front],
                    [ aspect/2, -0.5, z_back ],
                    [-aspect/2, -0.5, z_back ],
                ], dtype=np.float32),
                uv=np.array([
                    [0.0, 0.0], [1.0, 0.0],
                    [1.0, s  ], [0.0, s  ],
                ], dtype=np.float32),
            ),
        ]

        for p in panels:
            pm = trimesh.Trimesh(
                vertices=p["verts"],
                faces=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
                process=False,
            )
            pm.visual = trimesh.visual.TextureVisuals(uv=p["uv"], material=_make_material())
            scene_meshes.append(pm)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    trimesh.Scene(scene_meshes).export(out_path)

    n_verts, n_faces = len(verts), len(faces_arr)
    print(f"[depth_cloud] {n_verts:,} verts {n_faces:,} faces + bg + wings → {out_path}")
    return out_path

