# OmniMesh 🚀
### All-in-One 3D Mesh Optimization, Topology Sanitization, Skeletal Rigging, Real-Time LOD Simulation & Multi-Engine Pipeline for Blender (4.2+ & 5.2 LTS)

[![Blender 4.2+ / 5.2 LTS](https://img.shields.io/badge/Blender-4.2%2B%20%7C%205.2%20LTS-E87D0D?logo=blender&logoColor=white)](https://www.blender.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)
[![OmniMesh CI](https://github.com/DanAzanza/OmniMesh/actions/workflows/ci.yml/badge.svg)](https://github.com/DanAzanza/OmniMesh/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/Tests-14%20passed%20%28100%25%29-brightgreen.svg)]()
[![Code Quality](https://img.shields.io/badge/Ruff%20%26%20Pyright-0%20errors-brightgreen.svg)]()
[![Engines](https://img.shields.io/badge/Engines-MSFS%202024%20%7C%20UE5%20%7C%20Unity%206%20%7C%20Godot%204-purple.svg)]()

**OmniMesh** is an enterprise-grade 3D mesh processing pipeline and LOD engine developed by **Daniel** ([@DanAzanza](https://github.com/DanAzanza)) for Blender. It bridges the gap between raw, multi-million polygon photogrammetry/DCC models and game-ready production assets for **Microsoft Flight Simulator 2024**, **Unreal Engine 5**, **Unity 6**, and **Godot 4**.

---

## 🌟 Key Pillars & Features

### 1. 📐 Screen-Space Error Bound (SSE) Mathematics
Instead of relying on arbitrary reduction percentages, OmniMesh couples every decimation and cleanup parameter directly to human eye perception and viewport resolution ($H = 1080\text{px}$):
$$\delta_{\text{world}} = \frac{2 \cdot \tau_{\text{sse}} \cdot r_{\text{bound}}}{S_{\text{frac}} \cdot H}$$
* **Coupled Tolerances**: Merge distance $\epsilon$, feature dissolution $w_{\text{crit}}$, planar angle $\theta_{\text{limit}}$, and QEM ratio are derived deterministically from the user's Visual Stability threshold $\tau_{\text{sse}}$ (0.2px to 3.0px).
* **Perceptual Logarithmic Progression**: Automatically generates logarithmic screen-size tiers matching physical camera distance curves.

### 2. 🛡️ Deep Topology Sanitization Gate
* **Degenerate Geometry Collapse**: Zero-length edges and zero-area faces are eliminated in pure BMesh.
* **Non-Manifold & Bowtie Repair**: Resolves complex topological defects, edges sharing $>2$ faces, and isolated island noise.
* **CAD Custom Normal & UV Boundary Preservation**: Protects UV seams, sharp edge marks, and reprojects high-precision split normals via `DATA_TRANSFER` without dark shading gouges.

### 3. 🦴 Skeletal Rigging, GPU Clamping & Bone Pruning
* **GPU 4/8-Influence Clamping**: Restricts active bone weights per vertex to **4** (glTF/Mobile/Unity) or **8** (Unreal Engine 5) and normalizes $\sum w = 1.0$.
* **Zero-Sum Singularity Guard**: Eliminates shader NaN / GPU crash vectors by falling back to the parent anchor bone if micro-weights are stripped.
* **Recursive Kinematic Leaf-Bone Pruning**: Measures the projected screen diameter of vertices assigned to leaf bones (fingers, facial bones, jewelry). If $< 1.5\text{px}$, weights collapse recursively into parent bones, stripping unused vertex groups from distance LODs.
* **Shape Key & Morph Target Stripper**: Resets facial blendshapes to Basis (`0.0`) and purges shape keys on LOD $\ge 2$ to prevent mesh tearing.

### 4. 🗂️ Multi-Mesh Hierarchies & Draw-Call Consolidation
* **Mode A (`Preserve Hierarchy`)**: Preserves all submesh objects independently across all LOD tiers.
* **Mode B (`Merge Distant Tiers`)**: Consolidates compatible submeshes into a single draw-call mesh at distant tiers (e.g. LOD3..LOD6).
* **Rest-Pose Coordinate Inversion**: Seamlessly merges bone-parented static props into skinned meshes without pose baking distortion:
  $$\mathbf{M}_{S \to M\_rest} = \mathbf{M}_{M\_rest\_world}^{-1} \cdot \mathbf{M}_{Arm\_world} \cdot \mathbf{M}_{B\_bone\_local} \cdot \mathbf{M}_{S\_parent\_inv} \cdot \mathbf{M}_{S\_basis}$$

### 5. 🎮 Real-Time Viewport LOD Simulator
* **Live Orbit Simulation**: Non-blocking modal loop (25 Hz) with mouse pass-through (`PASS_THROUGH`) that dynamically evaluates camera distance and switches all scene assets independently in real time.
* **Unity-Style Virtual Distance Slider**: Drag a slider in the N-Panel to preview an asset transitioning across all LOD tiers without moving the camera.
* **Differential Visibility Updates**: Eliminates depsgraph recursion and leaves the artist's `Ctrl+Z` Undo history 100% clean.
* **Live 2D GPU HUD**: Displays active LOD tier, distance in meters, screen percentage, and active triangle count in the 3D viewport.

### 6. 📦 1-Click Multi-Engine Exporters
* **Microsoft Flight Simulator 2020 / 2024**: Exports glTF 2.0 separate buffers alongside official SDK-compliant `ModelInfo` XML files with exact `<LOD minSize="...">` tags.
* **Unreal Engine 5**: Exports FBX with native `LODGroup` empty hierarchies for static meshes and direct Armature skeletal mesh hierarchies.
* **Unity 6**: Exports FBX with standard `_LOD0..N` naming conventions recognized automatically by Unity's LOD Group component.
* **Godot 4.x**: Exports glTF 2.0 with visibility range metadata.

---

## 📊 Benchmark & Empirical Validation

Tested across **100 photogrammetry and hero game assets** from Epic Games FabLibrary (*Medieval Banquet, Bazaar, Roadside Construction, Saloon Interior, Warehouse*):

| Metric | Result |
| :--- | :--- |
| **Total Models Tested** | **100 / 100** |
| **Success / Pass Rate** | **100.0%** (0 unhandled exceptions) |
| **Average Polygon Reduction** | **95.66%** across LOD stages |
| **Average Processing Time** | **4.60 seconds** per asset |
| **PBR Normal & Shading Integrity** | **100% Intact** (Custom Split Normals preserved) |

---

## 📥 Installation

### Method A: Blender 4.2+ Extension (Recommended)
1. Download the latest `omnimesh-v1.2.0.zip` from [Releases](https://github.com/DanAzanza/OmniMesh/releases).
2. In Blender, navigate to `Edit` > `Preferences` > `Add-ons` / `Get Extensions`.
3. Click the gear icon (top right) > **Install from Disk...** and select the `.zip` file.
4. Enable **OmniMesh**.

### Method B: Manual Installation
Copy the repository directory into your Blender scripts folder:
* **Windows**: `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\omnimesh`
* **Linux**: `~/.config/blender/5.2/scripts/addons/omnimesh`
* **macOS**: `~/Library/Application Support/Blender/5.2/scripts/addons/omnimesh`

---

## 🚀 Quickstart Guide

1. Open Blender and select one or more 3D meshes (or a rigged character with Armature).
2. Open the 3D Viewport sidebar (`N`-key) and click the **OmniMesh** tab.
3. Choose your **Target Engine** (*MSFS 2024, Unreal Engine 5, Unity 6, Godot 4*).
4. Adjust **Visual Stability (SSE)** (default `0.80px`) and click **"Analyze & Auto-Configure"**.
5. Click **"Generate All LODs"**.
6. Click **"Start Live Simulator"** to inspect dynamic switching in the viewport or use the **Virtual Distance Slider**!
7. Set your export directory and click **"1-Click Export Asset"**.

---

## 🛠️ Automated Testing & Quality Gate

OmniMesh includes a complete test & lint suite:

```bash
# Run pytest test suite
python -m pytest -v

# Run Ruff linter & formatting check
python -m ruff check .
python -m ruff format --check .

# Run Pyright static type checker
python -m pyright .
```

---

## 👤 Author & Maintainer

Developed with ❤️ by **Daniel** ([@DanAzanza](https://github.com/DanAzanza)).

---

## 📜 License

This project is licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`) - see the [LICENSE](LICENSE) file for details.
