window.HARDWARE = {
  "colors": {
    "power": "#cf572c",
    "spi": "#7554b3",
    "sensor": "#217d61",
    "usb": "#3264aa",
    "pending": "#7a7f77",
    "ac": "#b43f36",
    "secondary": "#c57921"
  },
  "parts": [
    {
      "id": "enclosure",
      "n": "01",
      "name": "Controller enclosure",
      "short": "Controller enclosure",
      "category": "MECHANICAL",
      "location": "Left side of the baseboard",
      "spec": "Standard insulated box sized for the controller and sensor boards; insulated standoffs",
      "purpose": "Holds USB-powered controller electronics and compatible low-voltage interfaces. The transformer primary and AC source belong in a separate guarded compartment.",
      "notes": [
        "Lay out the purchased boards on paper and check cable bend space before choosing the box.",
        "Mount the electronics on 8–12 mm insulated standoffs; route power along one edge and sensors along the other.",
        "Use cable glands, ferrules and matching labels at both ends of each cable."
      ],
      "warning": "The model shows functional zones, not certified clearance distances. Do not put exposed 220/230 V wiring in this controller box.",
      "pos": [
        -195,
        8,
        5
      ],
      "lift": [
        0,
        0,
        0
      ]
    },
    {
      "id": "power",
      "n": "02",
      "name": "College AC supply & protected inlet",
      "short": "College AC supply",
      "category": "CHOSEN ARCHITECTURE",
      "location": "Technician-prepared, enclosed mains section",
      "spec": "Existing college 230 V / 50 Hz AC supply; borrow an enclosed transformer trainer first",
      "purpose": "Uses the AC supply already available. This block represents the protected supply connection, not another converter to buy.",
      "notes": [
        "Preferred: borrow an enclosed 230 V to 12 V AC transformer trainer from the college lab. Confirm permission to use it at the venue.",
        "Alternative: have the lab technician assemble and check the proposed transformer in a suitable protected enclosure. Primary terminals must remain inaccessible.",
        "The inverter, battery and battery-fed buck are removed. Primary hobby-sensor modules are deferred; the core build measures the secondary."
      ],
      "warning": "The architecture is selected, not electrically commissioned. A qualified lab technician must check enclosure, protection, disconnect, earthing/isolation and the completed assembly before use.",
      "pos": [
        -235,
        27,
        180
      ],
      "lift": [
        -25,
        20,
        30
      ],
      "status": "LAB SETUP",
      "source": "https://www.hse.gov.uk/electricity/withequip.htm",
      "sourceLabel": "Electrical-work competence guidance ↗"
    },
    {
      "id": "mcu",
      "n": "03",
      "name": "ESP32-S3 controller",
      "short": "ESP32-S3",
      "category": "CONTROLLER",
      "location": "Rear-left, USB connectors accessible",
      "spec": "ESP32-S3-DevKitC-1; verify module variant and pin labels",
      "purpose": "Laptop USB supplies the ESP32 development board and carries serial telemetry. Its GPIO handles only compatible sensor and driver signals.",
      "notes": [
        "Keep the confirmed laptop USB → ESP32 USB-socket supply. Leave external 5 V and 3.3 V power feeds disconnected.",
        "SPI SCK12 / MOSI11 / MISO13 serves the two MAX31865 boards, with CS10 for surface and CS14 for ambient. Verify the regulator current budget.",
        "Two secondary AC measurement channels and three relay-control pins are pending a module-specific interface review. No 5 V analog output or raw AC conductor connects directly to a GPIO."
      ],
      "warning": "The new analog front end, relay driver mapping, firmware and live ingestion adapter remain pending. A USB cable does not isolate the laptop from a wiring fault.",
      "source": "https://docs.espressif.com/projects/esp-idf/en/v4.4.3/esp32s3/hw-reference/esp32s3/user-guide-devkitc-1.html",
      "pos": [
        -268,
        23,
        -32
      ],
      "lift": [
        -32,
        58,
        -28
      ],
      "status": "USB POWER"
    },
    {
      "id": "rtd1",
      "n": "04",
      "name": "RTD converter · surface",
      "short": "MAX31865 A",
      "category": "TEMPERATURE",
      "location": "Inside the controller enclosure",
      "spec": "PT100-compatible MAX31865; verify reference resistor",
      "purpose": "Converts the transformer surface PT100 resistance into a temperature reading. It does not directly measure winding hot-spot temperature.",
      "notes": [
        "Use SCK12, MOSI11, MISO13 and CS10. Power this 3.3 V signal domain from a compatible supply.",
        "Set board jumpers and firmware for the exact 3-wire probe topology. Identify the same-end pair with a meter.",
        "Record the fitted reference resistor; Adafruit PT100 boards use 430 Ω. Clone boards can differ."
      ],
      "warning": "Report TRANSFORMER EXTERIOR temperature. This channel does not directly measure oil or winding hot-spot temperature.",
      "source": "https://learn.adafruit.com/adafruit-max31865-rtd-pt100-amplifier/rtd-wiring-config",
      "pos": [
        -197,
        22,
        -39
      ],
      "lift": [
        0,
        70,
        -30
      ]
    },
    {
      "id": "rtd2",
      "n": "05",
      "name": "RTD converter · ambient",
      "short": "MAX31865 B",
      "category": "TEMPERATURE",
      "location": "Inside the controller enclosure, beside the surface converter",
      "spec": "Second MAX31865 with separate CS14",
      "purpose": "Reads the second PT100 in room air, providing the thermal model with an ambient reference.",
      "notes": [
        "Share SCK12, MOSI11 and MISO13 with converter A; use CS14, not CS10.",
        "Place the ambient probe in room air away from the transformer and resistor bank.",
        "Check the probes side by side first. After installation they measure different locations, not redundant oil measurements."
      ],
      "warning": "This is the room-temperature reference. Do not place it against the enclosure or a warm component.",
      "source": "https://learn.adafruit.com/adafruit-max31865-rtd-pt100-amplifier/rtd-wiring-config",
      "pos": [
        -135,
        22,
        -39
      ],
      "lift": [
        32,
        85,
        -30
      ]
    },
    {
      "id": "transformer",
      "n": "06",
      "name": "12-0-12 V step-down transformer",
      "short": "Step-down transformer",
      "category": "TRANSFORMER UNDER TEST",
      "location": "Centre-rear, inside a separate guarded power compartment",
      "spec": "Electronic Spices 230 V AC → 12-0-12 V AC, listed 1.5 A, 50–60 Hz; verify actual winding / VA ratings",
      "purpose": "Provides a real small-transformer load experiment. This bench is not an oil-filled distribution transformer.",
      "notes": [
        "Use the existing college AC supply through the technician-prepared protected assembly, or borrow a suitable enclosed transformer trainer. No inverter is needed.",
        "The load planner assumes ONE nominal 12 V winding section, not the 24 V end-to-end pair. Confirm terminals and allowable current on the purchased unit.",
        "A qualified lab technician must review and enclose primary connections, fusing, cable retention, thermal cutoff and the supply disconnect before use."
      ],
      "warning": "Do not reverse-feed the low-voltage winding or treat the centre tap as protective earth. The 3D model is not a terminal wiring diagram.",
      "pos": [
        80,
        24,
        -58
      ],
      "lift": [
        0,
        45,
        -20
      ],
      "status": "PROPOSED",
      "source": "https://electronicspices.com/product/12-0-12-12v-1-5amp-center-tapped-step-down-transformer/",
      "sourceLabel": "Transformer manufacturer specifications ↗"
    },
    {
      "id": "probe",
      "n": "07",
      "name": "Transformer surface PT100",
      "short": "Surface PT100",
      "category": "SENSOR",
      "location": "Approved insulated fixture on the transformer exterior",
      "spec": "3-wire PT100; insulated clamp with good thermal contact",
      "purpose": "Tracks transformer exterior temperature independently of ambient temperature.",
      "notes": [
        "Have the hardware lead choose an electrically insulated mounting position away from live terminals and windings.",
        "Connect the 3-wire probe to MAX31865 A, CS10, following the exact board guide.",
        "Compare with a reference thermometer. Record probe location and contact method for repeatable tests."
      ],
      "warning": "Surface temperature is not winding hot-spot or oil temperature. Do not insert a conductive probe into an energised transformer.",
      "source": "https://learn.adafruit.com/adafruit-max31865-rtd-pt100-amplifier/rtd-wiring-config",
      "pos": [
        82,
        69,
        -52
      ],
      "lift": [
        -5,
        80,
        10
      ]
    },
    {
      "id": "ambient",
      "n": "08",
      "name": "Room-temperature sensor",
      "short": "Room temperature",
      "category": "SENSOR",
      "location": "In room air, away from the transformer and load-bank heat",
      "spec": "Second 3-wire PT100, physically separated from heat source",
      "purpose": "Provides the ambient input listed in the problem statement. Surface minus ambient temperature shows the transformer’s rise above room temperature.",
      "notes": [
        "Support the cable with an insulating clip; keep the sensing tip exposed to room air and away from warm surfaces. No large stand is required.",
        "Route its cable to MAX31865 B through a labelled gland.",
        "Compare both probes at a common stable temperature before installing them in separate locations."
      ],
      "warning": "Use the same sampling timestamp and actual elapsed time for the thermal model; do not speed up the hardware time axis.",
      "pos": [
        -345,
        18,
        -90
      ],
      "lift": [
        -15,
        45,
        -15
      ]
    },
    {
      "id": "laptop",
      "n": "09",
      "name": "Laptop USB power & telemetry",
      "short": "Laptop / USB",
      "category": "SOFTWARE HANDOFF",
      "location": "Outside the physical assembly",
      "spec": "Existing NeuraTwin app + a new serial/Wi-Fi ingestion adapter",
      "purpose": "USB powers the controller and can carry future measured packets. The current console remains replay/import based.",
      "notes": [
        "Use a USB data cable between laptop and development-board USB port. Leave the ESP32 external power pins unpowered.",
        "Build the BENCH-001 adapter with primary/secondary AC RMS voltage/current, transformer exterior and ambient temperatures, units and quality flags. Real watts require valid waveform processing.",
        "Keep NR-104 transformer replay separate. Implement AC acquisition, sensor quality flags and confirmation of load changes before claiming live integration."
      ],
      "warning": "AC acquisition, load-response confirmation and a separate BENCH-001 model still require implementation. Do not label simulated readings as live.",
      "pos": [
        320,
        38,
        -104
      ],
      "lift": [
        20,
        15,
        -15
      ],
      "status": "CONFIRMED"
    },
    {
      "id": "loadbank",
      "n": "10",
      "name": "Three parallel resistor loads",
      "short": "3 × resistor bank",
      "category": "PROPOSED LOAD",
      "status": "12 V AC PLAN",
      "location": "Centre-front, on a dedicated heatsink under a vented guard",
      "spec": "3 × 68 Ω / 50 W chassis resistors on a guarded heatsink; three secondary-side relay contacts. 33 Ω is an alternative to review.",
      "purpose": "Creates repeatable low-voltage resistive load steps on the transformer secondary.",
      "notes": [
        "Default calculation at 12 V RMS: each 68 Ω branch draws 0.176 A and dissipates 2.12 W. Three branches draw 0.529 A / 6.35 W.",
        "The optional 33 Ω candidate gives 0.364 A / 4.36 W per branch, or 1.091 A / 13.09 W for three. Verify actual winding rating, voltage, fusing and resistor mounting first.",
        "All branches are parallel. Each branch has its own series relay contact; all return to the other terminal of the same 12 V secondary section."
      ],
      "warning": "Planner toggles do not operate hardware. Do not connect these loads across 220/230 V or assume the old 24 V DC calculations still apply.",
      "source": "https://www.ohmite.com/arcolresistors/hs-aluminum-housed/",
      "pos": [
        100,
        25,
        125
      ],
      "lift": [
        0,
        35,
        15
      ]
    },
    {
      "id": "senseout",
      "n": "11",
      "name": "Secondary AC measurement interface",
      "short": "Secondary sensing",
      "category": "SENSOR REVIEW",
      "status": "CANDIDATE",
      "location": "Before the three parallel load branches",
      "spec": "1 × ACS712 5 A + 1 × ZMPT101B candidate; calibrate for actual secondary current and nominal 12 V AC",
      "purpose": "Measures secondary RMS voltage and total load current, independently of relay commands.",
      "notes": [
        "Current sensor in series with the load feed; voltage sensor across the chosen 12 V winding section.",
        "Verify ZMPT101B low-voltage gain and calibrate against reference instruments. Test zero, one, two and three branches.",
        "ACS712 requires its specified supply and output conditioning. Do not assume any 5 V module output is directly ESP32-compatible."
      ],
      "warning": "Compute RMS from sampled waveforms. Vrms × Irms is apparent power (VA). Without input real-power measurement, do not report measured transformer efficiency or input losses.",
      "pos": [
        155,
        23,
        35
      ],
      "lift": [
        0,
        45,
        0
      ],
      "source": "https://www.allegromicro.com/-/media/files/datasheets/acs712-datasheet.ashx"
    },
    {
      "id": "relays",
      "n": "12",
      "name": "Three secondary-side relay modules",
      "short": "3 × load relays",
      "category": "LOAD CONTROL",
      "spec": "3 × proposed 5 V relay modules; verify 3.3 V input compatibility and AC contact ratings",
      "purpose": "One normally-open contact per load branch; firmware requests are separate from measured current.",
      "notes": [
        "Power relay coils from a verified auxiliary supply, not an ESP32 GPIO.",
        "Use a compatible transistor/optocoupler interface if required. Relay control pins remain unassigned until the exact module is checked.",
        "Default all loads off at boot and on telemetry/control failure. Independent overcurrent/thermal protection must still operate."
      ],
      "warning": "A relay marked 10 A does not make the transformer a 10 A source. The figure shows three independent secondary branches, not primary switching.",
      "pos": [
        -32,
        22,
        122
      ],
      "lift": [
        0,
        50,
        12
      ],
      "source": "https://robu.in/product/1-channel-5v-10a-relay-control-board-module-optocoupler/",
      "status": "PENDING",
      "location": "Separate low-voltage service area; final placement to verify"
    },
    {
      "id": "conditioning",
      "n": "13",
      "name": "Analog conditioning & relay drivers",
      "short": "Signal interface",
      "category": "INTERFACE PENDING",
      "spec": "Two secondary AC measurement inputs; ESP32-compatible conditioning / ADC and three relay drivers to select",
      "purpose": "Keeps the reviewed low-voltage sensor outputs inside the ESP32 input range.",
      "notes": [
        "Specify sensor supply, offset, maximum waveform amplitude, attenuation, filtering and input protection before assigning ADC pins.",
        "Verify all analog interfaces with a meter/scope before MCU connection. This is not a bare 220 V resistor divider.",
        "Document grounding/isolation. Output real watts require time-aligned voltage/current and phase calibration; secondary measurements alone do not establish transformer efficiency."
      ],
      "warning": "No ready-to-wire ADC or relay pin map exists for the newly proposed modules. The grey routes are interface placeholders.",
      "pos": [
        -48,
        24,
        34
      ],
      "lift": [
        -10,
        75,
        0
      ],
      "source": "https://documentation.espressif.com/esp32-s3_datasheet_en.pdf",
      "status": "PENDING",
      "location": "Separate low-voltage service area; final placement to verify"
    },
    {
      "id": "aux",
      "n": "14",
      "name": "Separate regulated DC module supply",
      "short": "Regulated DC supply",
      "category": "AUXILIARY POWER",
      "spec": "Separate enclosed, regulated 5 V DC supply for compatible relay / sensor modules; size after checking their total current",
      "purpose": "Powers relay coils and compatible sensor electronics independently of the laptop-powered ESP32.",
      "notes": [
        "Borrow a suitable regulated lab DC supply or select an enclosed 5 V DC adapter. Verify voltage, current, connector polarity and ripple against each module.",
        "12 V AC is not 12 V DC. Do not feed it into relay power inputs, the ESP32 or an ordinary DC buck converter.",
        "Keep USB as the ESP32 power source. Review signal references / isolation and prevent back-feeding."
      ],
      "warning": "Exact supply rating and grounding / isolation arrangement remain pending. Relay coils must not be powered from GPIOs.",
      "pos": [
        -85,
        23,
        190
      ],
      "lift": [
        10,
        50,
        25
      ],
      "source": "",
      "status": "PENDING",
      "location": "Separate low-voltage service area; final placement to verify"
    }
  ],
  "connections": [
    [
      "laptop",
      "mcu",
      "usb",
      "Laptop USB port → ESP32 USB socket: power + serial data",
      "USB powers only the controller side. No buck feed to ESP32 5V / 3V3 pins."
    ],
    [
      "mcu",
      "rtd1",
      "power",
      "3V3 → compatible VIN; GND → GND",
      "Check exact module supply label and total 3.3 V regulator load."
    ],
    [
      "mcu",
      "rtd2",
      "power",
      "3V3 → compatible VIN; GND → GND",
      "Do not connect MAX31865 inputs to any energized conductor."
    ],
    [
      "mcu",
      "rtd1",
      "spi",
      "GPIO12 → CLK; GPIO11 → SDI; GPIO13 ← SDO; GPIO10 → CS",
      "Only this device’s CS goes low during its transaction."
    ],
    [
      "mcu",
      "rtd2",
      "spi",
      "GPIO12 → CLK; GPIO11 → SDI; GPIO13 ← SDO; GPIO14 → CS",
      "SCK/MOSI/MISO shared with surface converter A; separate CS14."
    ],
    [
      "probe",
      "rtd1",
      "sensor",
      "3-wire RTD → F / RTD terminals per board guide",
      "Identify the same-end pair using a meter; configure jumpers AND firmware."
    ],
    [
      "ambient",
      "rtd2",
      "sensor",
      "3-wire RTD → F / RTD terminals per board guide",
      "Separate CS14, matching reference resistor setting, and 3-wire mode."
    ],
    [
      "power",
      "transformer",
      "ac",
      "CONCEPT ONLY: college AC supply → technician-prepared protected transformer primary",
      "Borrow an enclosed trainer or have the lab technician prepare and verify the mains section. No inverter or primary hobby sensors in this build."
    ],
    [
      "transformer",
      "relays",
      "secondary",
      "Chosen nominal 12 V AC secondary → protection → three separate relay contacts",
      "Confirm the winding terminals and current rating; not the 24 V end-to-end pair."
    ],
    [
      "relays",
      "loadbank",
      "secondary",
      "Branch 1: relay K1 normally-open contact → R1 → same secondary return",
      "All three branches are parallel. Contacts and conductor/protection ratings need verification."
    ],
    [
      "relays",
      "loadbank",
      "secondary",
      "Branch 2: relay K2 normally-open contact → R2 → same secondary return",
      "All three branches are parallel. Contacts and conductor/protection ratings need verification."
    ],
    [
      "relays",
      "loadbank",
      "secondary",
      "Branch 3: relay K3 normally-open contact → R3 → same secondary return",
      "All three branches are parallel. Contacts and conductor/protection ratings need verification."
    ],
    [
      "transformer",
      "senseout",
      "pending",
      "Secondary voltage across chosen winding; total current in series before branches",
      "ACS712 / ZMPT101B candidates need calibration and range verification."
    ],
    [
      "senseout",
      "conditioning",
      "pending",
      "Low-voltage secondary sensor outputs → reviewed analog front end",
      "Attenuation, offset, filtering and input protection pending."
    ],
    [
      "conditioning",
      "mcu",
      "pending",
      "Conditioned secondary V / I data → MCU; two analog channel allocations pending",
      "ESP32-compatible input range and calibrated RMS sampling required before wiring."
    ],
    [
      "mcu",
      "relays",
      "pending",
      "Three load commands through compatible drivers; GPIOs not yet assigned",
      "Verify active-low/high behaviour and fail-off defaults; never drive coils from GPIO."
    ],
    [
      "aux",
      "relays",
      "pending",
      "Verified 5 V auxiliary supply → relay supply terminals",
      "Coil current budget, exact board jumpers and signal reference/isolation need review."
    ],
    [
      "aux",
      "conditioning",
      "pending",
      "Verified auxiliary supply → sensor/front-end power distribution",
      "Exact module supply limits and grounding are pending. No auxiliary feed into USB-powered MCU."
    ]
  ],
  "steps": [
    {
      "name": "Source",
      "title": "01. Borrow the protected transformer setup.",
      "body": "Ask the college lab for an enclosed 230 V to 12 V AC transformer trainer. If unavailable, have the lab technician prepare and check the proposed transformer assembly on the existing AC supply. No inverter, battery or battery-fed buck is needed.",
      "check": "Venue use is permitted. The technician verifies the nameplate, enclosed primary, protection and disconnect before energising.",
      "ids": [
        "power",
        "transformer"
      ],
      "explode": 15,
      "camera": "iso"
    },
    {
      "name": "Separate",
      "title": "02. Separate the power and signal compartments.",
      "body": "Keep the enclosed mains section separate from the USB controller and low-voltage load area. Confirm fuses, disconnect, strain relief, thermal protection and insulated probe mounting. Select a regulated DC supply for relay / sensor modules.",
      "check": "No primary conductor, mains divider or power return reaches the MCU. USB and external MCU power are not connected together.",
      "ids": [
        "enclosure",
        "conditioning",
        "aux"
      ],
      "explode": 45,
      "camera": "top"
    },
    {
      "name": "Loads",
      "title": "03. Build three low-voltage parallel loads.",
      "body": "Use the verified nominal 12 V secondary section. Fit one relay contact in series with each resistor branch and a common return to that same winding section. Guard the resistor heatsink; begin with all contacts off.",
      "check": "With power removed, branch continuity and default-off states match the reviewed schematic. Total load fits the actual winding rating.",
      "ids": [
        "relays",
        "loadbank",
        "transformer"
      ],
      "explode": 40,
      "camera": "iso"
    },
    {
      "name": "Sensing",
      "title": "04. Calibrate electrical and thermal sensing.",
      "body": "Use one secondary current channel and one secondary voltage channel. Verify ACS712 / ZMPT101B accuracy at the actual load and 12 V AC; condition their outputs for the ESP32. Compare sampled RMS readings with reference instruments. Fit surface and ambient PT100s.",
      "check": "The two analog outputs stay in the ADC range. Primary sensing is deferred. Surface readings are labelled as surface temperature, not oil or winding temperature.",
      "ids": [
        "senseout",
        "conditioning",
        "probe"
      ],
      "explode": 35,
      "camera": "iso"
    },
    {
      "name": "Interface",
      "title": "05. Verify the three relay drivers.",
      "body": "Confirm the relay driver compatibility, regulated DC supply budget and off-at-boot behaviour, then assign their GPIOs. The laptop dashboard is the only operator interface; no extra display or control panel is required.",
      "check": "All load branches default off. Independent protection works without the app. Confirm commanded load changes using measured secondary current.",
      "ids": [
        "relays",
        "mcu",
        "aux"
      ],
      "explode": 80,
      "camera": "iso"
    },
    {
      "name": "Connect",
      "title": "06. Implement the real acquisition path.",
      "body": "Build firmware and the live adapter for timestamped secondary RMS voltage/current, surface/ambient temperature and quality flags. Display Vrms × Irms as VA. Real watts need calibrated time-aligned waveforms; do not report measured efficiency without input real power. Fit BENCH-001 separately.",
      "check": "Physical changes drive measured traces. Stale/missing packets are visible. UI simulations never appear as live instrument readings.",
      "ids": [
        "laptop",
        "mcu",
        "senseout"
      ],
      "explode": 0,
      "camera": "iso"
    },
    {
      "name": "Prove it",
      "title": "07. Demonstrate an evidence-backed response.",
      "body": "Add safe load stages, show the measured response on the laptop, compare a proposed action and confirm an operator-approved load reduction. Record actual thermal response beforehand; use labelled replay if heating is too slow.",
      "check": "No deliberate short circuit or overload beyond the verified rating. Bench results are not presented as validated oil temperature, winding hot-spot or remaining life.",
      "ids": [
        "transformer",
        "loadbank",
        "laptop"
      ],
      "explode": 0,
      "camera": "iso"
    }
  ],
  "revision": "1.5",
  "load": {
    "voltage": 12,
    "resistance": 68,
    "ratedWatts": 50,
    "branches": 3,
    "alternativeResistance": 33
  }
};
