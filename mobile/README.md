# Halo mobile

Expo / React Native client for the existing NeuraTwin API. Opens the last selected
transformer directly, including on a first launch with no connection; no QR step. Light interface with four tabs:

- **Twin:** industrial simulation or ESP32 prototype readings, local interactive 3D
  model, animated health index with contributing factors, electrical waveforms,
  load/imbalance controls, fault injection and two-curve intervention comparison.
- **Alerts:** current signals, acknowledgment, protection holds and event history.
  Replay recorded events with synchronized temperature, health and waveforms.
- **Inspect:** camera/library photos, notes and independent surface readings. Save
  drafts locally or submit; queued submissions retry after reconnection without
  duplicating records. A draft remains attached to its original asset.
- **Assistant:** explanations grounded in the selected asset's current evidence.
  Uses the server's OpenAI key when configured; otherwise explicitly shows an
  evidence summary. The assistant cannot issue equipment commands.

Account provides opt-in critical notifications and report sharing. Simulation and
physical readings retain their different meanings; unavailable channels stay empty.

Industrial waveforms illustrate simulated three-phase RMS currents and neutral
current. Imbalance affects electrical stress, copper losses and thermal response.
Prototype waveforms illustrate primary/secondary RMS measurements; they are not
oscilloscope captures or measured phase angles. The ESP32 does not send waveform
buffers. Health is a screening index, not a probability of failure. Older recorded
history may lack phase channels or score contributions; those remain unavailable.
Dragging previews the electrical response immediately; releasing applies the
conditions to the simulation. Replay never issues simulation or hardware commands.

## Run

From the repository root, using the project's Python environment:

```powershell
python scripts/run_mobile_demo.py
```

This starts the shared backend on port 8765 and automatically configures the app's
connection in ignored `mobile/.env.local`. It reads `../env` when present, or an
explicit `--env-file` path, after the repository `.env`. The selected storage
backend and Supabase project come from that file. Physical controls stay disabled.

From this directory:

```powershell
npm ci
npm start
```

Open the app: it goes straight to the twin, without login, a server field, or an
access code. The phone must be able to reach the laptop over the same network.
The Expo tunnel carries the app bundle; it does not tunnel the Python API.
If using a separately hosted demo API, set `HALO_MOBILE_PUBLIC_URL` before starting
the demo launcher. This is build-time configuration, never an in-app setup step.

The launcher enables `HALO_MOBILE_DEMO=1`. Automatic sessions allow simulation
and mobile evidence actions, not hardware, membership or configuration writes.
For Supabase, they also require the explicit `HALO_LOCAL_OPERATOR=1` setting.
They are disabled whenever physical control is enabled. Supabase secret keys
and device credentials remain in the backend process and are never sent to Expo.
The app opens without waiting for the API or ESP32. The 3D model, tabs and control
panels remain browsable offline; readings are unavailable or explicitly cached.
Prototype inspection drafts can be saved before the first connection. The app
reconnects automatically and syncs queued evidence when the API returns.
OpenAI and database keys stay on the backend; no secrets are embedded in the app.

## Build

```powershell
npx expo run:android
```

For a standalone Android demo APK with a local Android SDK and compatible JDK:

```powershell
npm run sync-twin
npx expo prebuild --platform android --no-install
cd android
.\gradlew.bat :app:assembleRelease -PreactNativeArchitectures=arm64-v8a
```

The local APK is in `android/app/build/outputs/apk/release/app-release.apk`.
On Windows, build from a short directory such as `C:\halo-native-build\mobile`;
long paths can prevent Ninja from reading generated native dependency files.
Expo's generated local release configuration uses a debug signing key; use your
own release signing credentials for distribution. `eas.json` also supplies
development, internal APK preview, and production profiles:

```powershell
npx eas-cli build --platform android --profile preview
```

EAS requires your Expo account/project. iOS native builds require macOS/Xcode or
an EAS build; installing on a physical iPhone requires appropriate signing.
LAN HTTP is permitted for local demonstrations; public URLs must use HTTPS.

## Browser preview and checks

```powershell
npm run typecheck
npm run sync-twin
npx expo export --platform all
```

From the repository root, with the API running:

```powershell
python scripts/preview_mobile.py
```

Open `http://127.0.0.1:8082`. This serves the Expo web export and proxies its API
requests locally. It is a browser preview, not proof of native camera or push delivery.

## Push notifications

Link an EAS project and configure FCM/APNs credentials, then install a development
or standalone build. Remote push is not an Expo Go Android feature. In Settings,
enable notifications for the selected asset; registering another replaces the
device's previous asset subscription. Start the demo API with `--push`, or set
`HALO_PUSH_ENABLED=1` on the API server, to enable delivery. Notifications are sent
only to explicitly registered devices. The worker records Expo acceptance, not
confirmed device delivery. End-to-end push requires a configured physical device.

## Shared evidence

Inspections use the existing private record/photo storage; no new Supabase schema
is needed. They are available through `/api/halo/mobile/inspections` and appear in
web Maintenance. Saving or acknowledging never clears protection or verifies a repair.
Native code is generated by Expo; shared 3D geometry is regenerated from `../web`
by `npm run sync-twin`, without runtime CDN dependencies.
