"""Bench contracts: real units, explicit provenance and no invented GPIOs."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Frame(Contract):
    device_id: str = Field(pattern=r'^[\w-]{1,48}$')
    boot_id: str = Field(pattern=r'^[\w-]{1,64}$')
    sequence: int = Field(ge=0)
    uptime_ms: int = Field(ge=0)
    timestamp: datetime
    primary_v: float | None = Field(default=None, ge=0, le=300)
    secondary_v: float | None = Field(default=None, ge=0, le=60)
    current_a: float | None = Field(default=None, ge=0, le=30)
    primary_current_a: float | None = Field(default=None, ge=0, le=30)
    surface_c: float | None = Field(default=None, ge=-55, le=125)
    ambient_c: float | None = Field(default=None, ge=-30, le=80)
    ambient_source: Literal['not_measured', 'probe', 'manual'] = 'not_measured'
    ambient_observed_at: datetime | None = None
    relay_states: tuple[bool, bool, bool, bool] = (False, False, False, False)
    relay_output_configured: bool = False
    calibration_id: str | None = Field(default=None, max_length=80)
    config_id: str | None = Field(default=None, pattern=r'^CFG-[a-f0-9]{64}$')
    hardware_config_status: Literal['reported_match','mismatch','unverified'] = 'unverified'
    quality_flags: list[str] = Field(default_factory=list, max_length=16)
    raw: dict[str, float | None] = Field(default_factory=dict, max_length=20)

    @field_validator('timestamp')
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError('Timestamp needs a timezone.')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def ambient_origin(self):
        if self.ambient_c is not None and self.ambient_source == 'not_measured':
            raise ValueError('An ambient value needs an explicit probe or manual source.')
        if self.ambient_c is not None and self.ambient_source=='manual':
            if self.ambient_observed_at is None or self.ambient_observed_at.utcoffset() is None:
                raise ValueError('Manual ambient needs a timezone-aware observation time.')
            if not 0 <= (self.timestamp-self.ambient_observed_at).total_seconds() <= 600:
                raise ValueError('Manual ambient reference must precede acquisition by at most 10 minutes.')
        return self


class BenchConfig(Contract):
    name: str = Field(default='Halo physical demonstrator', min_length=1, max_length=90)
    device_id: str = Field(default='HALO-ESP32', pattern=r'^[\w-]{1,48}$')
    board: Literal['UNKNOWN', 'ESP32', 'ESP32-S3'] = 'UNKNOWN'
    primary_verified: bool = False
    secondary_verified: bool = False
    protection_reviewed: bool = False
    pinmap_verified: bool = False
    relay_polarity_verified: bool = False
    adc_interfaces_verified: bool = False
    nominal_secondary_v: float | None = Field(default=None, gt=0, le=24)
    current_limit_a: float | None = Field(default=None, gt=0, le=1)
    surface_limit_c: float | None = Field(default=None, ge=30, le=80)
    resistor_ohms: tuple[float, float, float, float] = (39, 39, 39, 39)
    relay_pins: tuple[int | None, int | None, int | None, int | None] = (12, 14, 27, 26)
    primary_adc_pin: int | None = 4
    secondary_adc_pin: int | None = 5
    current_adc_pin: int | None = None
    primary_current_adc_pin: int | None = None
    automatic_cutoff_enabled: bool = False
    temperature_pin: int | None = None
    active_low: bool | None = None
    reviewer: str = Field(default='', max_length=100)
    review_note: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def verify_ranges(self):
        if any(not 10 <= r <= 1000 for r in self.resistor_ohms):
            raise ValueError('Load resistances must be 10–1000 ohms.')
        if self.pinmap_verified:
            pins = [*self.relay_pins, self.primary_adc_pin, self.secondary_adc_pin,
                    self.current_adc_pin, self.temperature_pin]
            if self.board == 'UNKNOWN' or any(p is None for p in pins):
                raise ValueError('Resolve chip identity and every assigned pin first.')
            if len(set(pins)) != len(pins):
                raise ValueError('GPIO assignments must be unique.')
            adc = [self.primary_adc_pin, self.secondary_adc_pin, self.current_adc_pin]
            if self.primary_current_adc_pin is not None:
                if self.primary_current_adc_pin in pins:
                    raise ValueError('Primary current must use a separate, verified ADC input.')
                adc.append(self.primary_current_adc_pin)
            if self.board == 'ESP32':
                # ADC1 only, even for the USB transport, to avoid later Wi-Fi conflict.
                if any(p not in range(32, 40) for p in adc):
                    raise ValueError('ESP32 profile requires verified ADC1 pins 32–39. GPIO5 has no ADC.')
                if any(p not in [*range(0, 6), *range(12, 20), 21, 22, 23, 25, 26, 27, 32, 33]
                       for p in [*self.relay_pins, self.temperature_pin]):
                    raise ValueError('Output/one-wire GPIO unavailable or input-only on ESP32.')
            else:
                if any(p not in range(1, 11) for p in adc):
                    raise ValueError('S3 profile requires verified ADC1 pins 1–10.')
                if any(p not in [*range(0, 19), 21, *range(38, 43), 47, 48]
                       for p in [*self.relay_pins, self.temperature_pin]):
                    raise ValueError('S3 pin may be reserved for flash/PSRAM/USB; choose verified exposed pins.')
        return self


class Calibration(Contract):
    id: str = Field(pattern=r'^[\w-]{1,80}$')
    reviewer: str = Field(min_length=2, max_length=100)
    note: str = Field(min_length=5, max_length=2000)
    primary_v_per_mv: float | None = Field(default=None, gt=0, le=100)
    secondary_v_per_mv: float | None = Field(default=None, gt=0, le=10)
    current_a_per_mv: float | None = Field(default=None, gt=0, le=1)
    current_noise_mv: float = Field(default=0, ge=0, le=1000)
    primary_current_a_per_mv: float | None = Field(default=None, gt=0, le=1)
    primary_current_noise_mv: float = Field(default=0, ge=0, le=1000)
    surface_offset_c: float = Field(default=0, ge=-10, le=10)
    surface_reference: str | None = Field(default=None, min_length=5, max_length=300)
    ambient_reference: str | None = Field(default=None, min_length=5, max_length=300)
    references: list[str] = Field(min_length=1, max_length=12)


class RelayRequest(Contract):
    states: tuple[bool, bool, bool, bool]
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')


class Observation(Contract):
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')
    kind: Literal['inspection', 'action', 'followup']
    note: str = Field(min_length=5, max_length=3000)
    component: Literal['transformer', 'surface', 'current', 'voltage', 'relay', 'controller'] = 'transformer'
    observed_at: datetime
    independent_surface_c: float | None = Field(default=None, ge=-55, le=125)
    finding: Literal['not_assessed', 'sensor_agrees', 'sensor_disagrees', 'airflow_obstructed', 'no_visible_issue'] = 'not_assessed'
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)

    @field_validator('observed_at')
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError('Observation timestamp must include a timezone.')
        return value.astimezone(timezone.utc)
