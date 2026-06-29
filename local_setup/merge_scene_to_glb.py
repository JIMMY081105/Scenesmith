#!/usr/bin/env python3
"""Merge a SceneSmith Drake-directive scene (scene.dmd.yaml) into ONE .glb file.

The pipeline does not emit a single combined mesh for the whole room. This
script reads the scene directive (which lists each model's SDF + world pose),
pulls the *visual* glTF meshes out of every SDF (skipping collision .obj),
applies the SDF poses, and writes a single `combined_scene.glb` you can drag
into any glTF viewer (e.g. https://gltf-viewer.donmccurdy.com) or Blender.

Usage (inside WSL, with .venv active):
    python local_setup/merge_scene_to_glb.py            # auto-find newest run
    python local_setup/merge_scene_to_glb.py <path/to/scene.dmd.yaml>
    python local_setup/merge_scene_to_glb.py <dmd> -o out.glb --keep-zup

Only needs trimesh + numpy + pyyaml (already in .venv). No API key needed.
"""

import argparse
import sys
import xml.etree.ElementTree as ET

from glob import glob
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import numpy as np
import trimesh
import yaml
from trimesh import transformations as tf


# --- YAML: tolerate Drake's custom !AngleAxis tag ---------------------------
def _angle_axis(loader, node):
    return loader.construct_mapping(node)


yaml.SafeLoader.add_constructor("!AngleAxis", _angle_axis)


# glTF meshes are authored Y-up; the SDF/Drake assembly is Z-up and expects each
# mesh rotated +90 deg about X (Y-up -> Z-up) before its pose is applied.
YUP_TO_ZUP = tf.rotation_matrix(np.pi / 2.0, [1, 0, 0])


def _floats(text, n):
    vals = [float(x) for x in str(text).split()]
    return (vals + [0.0] * n)[:n]


def _pose_matrix(pose_text):
    """SDF <pose> 'x y z roll pitch yaw' (meters, radians) -> 4x4."""
    x, y, z, r, p, yw = _floats(pose_text, 6)
    T = tf.translation_matrix([x, y, z])
    R = tf.euler_matrix(r, p, yw, "sxyz")
    return T @ R


def _model_matrix(x_pc):
    """dmd add_weld X_PC (translation + axis-angle degrees) -> 4x4."""
    if not x_pc:
        return np.eye(4)
    t = x_pc.get("translation", [0, 0, 0])
    T = tf.translation_matrix(t)
    rot = x_pc.get("rotation")
    R = np.eye(4)
    if isinstance(rot, dict):
        angle = float(rot.get("angle_deg", 0.0))
        axis = rot.get("axis", [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) > 0 and angle != 0.0:
            R = tf.rotation_matrix(np.radians(angle), axis)
    return T @ R


def _uri_to_path(uri, base_dir):
    """Resolve an SDF/dmd <uri> (file:// or relative) to an absolute Path."""
    if uri.startswith("file://"):
        return Path(url2pathname(urlparse(uri).path))
    return (base_dir / uri).resolve()


def _parse_sdf_visuals(sdf_path):
    """Yield (mesh_path, scale[3], local_4x4) for each *visual* glTF in an SDF.

    Skips <collision> geometry. local transform = link_pose @ visual_pose.
    """
    sdf_path = Path(sdf_path)
    base = sdf_path.parent
    root = ET.parse(sdf_path).getroot()

    for link in root.iter("link"):
        link_pose_el = link.find("pose")
        link_T = _pose_matrix(link_pose_el.text) if link_pose_el is not None else np.eye(4)

        for visual in link.findall("visual"):
            mesh_el = visual.find("./geometry/mesh")
            if mesh_el is None:
                continue
            uri_el = mesh_el.find("uri")
            if uri_el is None:
                continue
            mesh_path = _uri_to_path(uri_el.text.strip(), base)

            scale_el = mesh_el.find("scale")
            scale = _floats(scale_el.text, 3) if scale_el is not None else [1.0, 1.0, 1.0]

            v_pose_el = visual.find("pose")
            v_T = _pose_matrix(v_pose_el.text) if v_pose_el is not None else np.eye(4)

            yield mesh_path, scale, link_T @ v_T


def _find_latest_dmd():
    """Newest renders_*/scene.dmd.yaml under outputs/."""
    candidates = glob("outputs/**/scene.dmd.yaml", recursive=True)
    if not candidates:
        return None
    return max(candidates, key=lambda p: Path(p).stat().st_mtime)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dmd", nargs="?", help="Path to scene.dmd.yaml (default: newest under outputs/)")
    ap.add_argument("-o", "--output", help="Output .glb (default: combined_scene.glb next to the dmd)")
    ap.add_argument("--keep-zup", action="store_true",
                    help="Keep Z-up. Default converts Z-up->Y-up so it stands upright in glTF viewers.")
    args = ap.parse_args()

    dmd_path = args.dmd or _find_latest_dmd()
    if not dmd_path or not Path(dmd_path).exists():
        sys.exit("ERROR: no scene.dmd.yaml found. Pass one explicitly.")
    dmd_path = Path(dmd_path).resolve()
    base_dir = dmd_path.parent
    print(f"[merge] scene directive: {dmd_path}")

    data = yaml.safe_load(dmd_path.read_text())
    directives = data.get("directives", [])

    # Collect models (name -> sdf path) and welds (model -> X_PC).
    models = {}
    welds = {}
    for d in directives:
        if "add_model" in d:
            m = d["add_model"]
            models[m["name"]] = _uri_to_path(m["file"], base_dir)
        elif "add_weld" in d:
            w = d["add_weld"]
            model_name = str(w["child"]).split("::")[0]
            welds[model_name] = w.get("X_PC")

    scene = trimesh.Scene()
    n_meshes = 0
    for name, sdf_path in models.items():
        if not Path(sdf_path).exists():
            print(f"[merge]   ! missing SDF for {name}: {sdf_path}")
            continue
        model_T = _model_matrix(welds.get(name))
        for mesh_path, scale, local_T in _parse_sdf_visuals(sdf_path):
            if not Path(mesh_path).exists():
                print(f"[merge]   ! missing mesh: {mesh_path}")
                continue
            loaded = trimesh.load(mesh_path, process=False)
            mesh = loaded.dump(concatenate=True) if isinstance(loaded, trimesh.Scene) else loaded
            S = np.diag([scale[0], scale[1], scale[2], 1.0])
            mesh.apply_transform(model_T @ local_T @ YUP_TO_ZUP @ S)
            scene.add_geometry(mesh, node_name=f"{name}_{n_meshes}")
            n_meshes += 1
        print(f"[merge]   + {name}")

    if n_meshes == 0:
        sys.exit("ERROR: no visual meshes were merged.")

    # glTF viewers are Y-up; the pipeline is Z-up. Rotate so it stands upright.
    if not args.keep_zup:
        scene.apply_transform(tf.rotation_matrix(-np.pi / 2.0, [1, 0, 0]))

    out = Path(args.output) if args.output else base_dir / "combined_scene.glb"
    scene.export(out)
    print(f"[merge] Merged {n_meshes} meshes from {len(models)} models.")
    print(f"[merge] Wrote: {out}")
    print(f"[merge] Windows path: \\\\wsl.localhost\\Ubuntu{str(out).replace('/', chr(92))}")


if __name__ == "__main__":
    main()
