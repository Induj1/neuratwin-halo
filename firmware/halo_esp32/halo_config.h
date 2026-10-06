#pragma once
// Commission only against the ACTUAL module markings and wiring. No mains test
// or upload is authorised by this file. GPIO12 is a classic ESP32 strapping pin.
constexpr bool PINMAP_VERIFIED = false;
constexpr bool ADC_INTERFACES_VERIFIED = false;
constexpr bool RELAY_POLARITY_VERIFIED = false;
constexpr bool PHYSICAL_CONTROL_ENABLED = false;
constexpr bool RELAY_ACTIVE_LOW = false; // UNKNOWN: replace only after verification.
constexpr int RELAY_PINS[4] = {12,14,27,26}; // Reported working assignments, not S3 defaults.
constexpr int PRIMARY_ADC = -1;   // UNKNOWN. Earlier GPIO4 is not ADC1 on classic ESP32.
constexpr int SECONDARY_ADC = -1; // UNKNOWN. Earlier GPIO5 has NO ADC on classic ESP32.
constexpr int CURRENT_ADC = -1;   // UNKNOWN. Verify 5 V sensor output conditioning.
constexpr int SURFACE_DATA = -1;  // UNKNOWN. 3.3 V DS18B20 + verified pull-up.
constexpr char DEVICE_ID[] = "HALO-ESP32";
constexpr unsigned long HOST_TIMEOUT_MS = 3000;
// Firmware is an auxiliary interlock, never an independent electrical protection.
