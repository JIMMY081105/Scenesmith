#!/usr/bin/env python3
"""View the SceneSmith room in Drake + MeshCat.

Put this file INSIDE the bundle folder (the one containing combined_house/,
room_geometry/, room_bedroom/, floor_plans/) and run:

    python drake_view_scene.py              # visual "outlook" (fast)
    python drake_view_scene.py collision    # collision hulls (slow: thousands of convex pieces)

It prints a MeshCat URL (http://localhost:7000). Open it in your browser.
"""
import os
import sys
import time

from pydrake.all import (
    RobotDiagramBuilder,
    StartMeshcat,
    MeshcatVisualizer,
    MeshcatVisualizerParams,
    Role,
    ProcessModelDirectives,
    LoadModelDirectives,
)

# Bundle root = the directory this script lives in.
SCENE = os.path.dirname(os.path.abspath(__file__))
DMD = os.path.join(SCENE, "combined_house", "house.dmd.yaml")
mode = sys.argv[1] if len(sys.argv) > 1 else "illustration"

builder = RobotDiagramBuilder()
plant = builder.plant()
parser = builder.parser()
parser.package_map().Add("scene", SCENE)          # package://scene/... -> bundle root
ProcessModelDirectives(LoadModelDirectives(DMD), plant, parser)
plant.Finalize()
print(f"Loaded scene OK: {plant.num_bodies()} bodies", flush=True)

meshcat = StartMeshcat()
role = Role.kProximity if mode == "collision" else Role.kIllustration
MeshcatVisualizer.AddToBuilder(
    builder.builder(), builder.scene_graph(), meshcat,
    MeshcatVisualizerParams(role=role),
)
diagram = builder.Build()
diagram.ForcedPublish(diagram.CreateDefaultContext())

print("\n=========================================")
print(f"  MeshCat ready ({mode}): {meshcat.web_url()}")
print("  Open that URL in your browser. Ctrl+C to stop.")
print("=========================================\n", flush=True)
while True:
    time.sleep(5)
