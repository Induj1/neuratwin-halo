#pragma once
// Copy this file to secrets.h (gitignored) and fill in the real values.

const char* WIFI_SSID     = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";

// Same value as HALO_DEVICE_TOKEN in the backend .env. Empty = no auth (LAN dev only).
// Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
const char* API_TOKEN     = "";
