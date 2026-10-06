# NeuraTwin Halo — Round 2 demo

NeuraTwin Halo is an evidence-aware digital twin console for distribution transformers. It turns a replayable telemetry stream into a live health index, thermal forecast, anomaly explanation, action comparison and traceable work order.

The command center includes a procedural WebGL transformer twin with drag interaction, a local cinematic substation scene, live sensor overlays and a static SVG fallback. The WebGL layer follows the browser renderer pattern documented by [Three.js](https://threejs.org/docs/pages/WebGLRenderer.html).

## Run locally

From this folder:

```powershell
python run.py --port 8765
```

Open `http://127.0.0.1:8765` for the cinematic product story, then choose **Open command center** or go directly to `http://127.0.0.1:8765/app` for the functional software console.

## Five-minute judge path

1. Click **Run 90-second demo** to launch Judge Mode, or start on **Live operations** and scrub the Twin Time Machine.
2. Open **Incident lab** and inject **Overload**, **Cooling loss**, **Sensor drift**, or **Telemetry dropout**.
3. Follow the causal evidence chain, then adjust load reduction and action delay to compare two possible futures.
4. Export an incident brief, create the recommended work order, and move it through the maintenance queue.
5. Finish in **Asset passport** to simulate an NFC field tap, export evidence JSON, or import a real CSV replay.

The demo is deliberately labelled as synthetic replay. Forecasts and hotspot values are estimates unless independently measured; the interface exposes that uncertainty instead of hiding it.

## Current hardware design — revision 1.5

Open `/static/hardware-guide.html` for the core college-AC transformer demo: protected transformer, secondary voltage/current measurement, surface and room temperature, three relay/resistor load branches, ESP32 and the necessary interfaces / supplies / enclosures. The laptop is the display and operator interface. Accessory fixtures and their wiring have been removed. Ambient measurement stays because it is in the problem statement and provides the temperature-rise reference.

Borrow an enclosed lab trainer first, or have a qualified lab technician prepare the proposed transformer assembly. ESP32 power stays on USB; relay / sensor modules need regulated DC. The analog interfaces, relay pin map, protection, firmware and live adapter still need implementation / verification. Earlier hardware guides describe superseded builds. Rebuild the portable viewer with `node hardware/package_3d_guide.cjs`; current notes are in `hardware/HARDWARE_REV15_START_HERE.txt`.
