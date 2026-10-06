"""Typed, unit-explicit contracts for the prototype and future telemetry adapters."""
from datetime import datetime
import math
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Asset(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,48}$')
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(max_length=100)
    rated_kva: float = Field(gt=0, le=100000)
    secondary_voltage_v: float = Field(default=415, gt=0)
    cooling: str = 'ONAN'
    rated_oil_rise_c: float = Field(default=48, gt=0, le=150)
    rated_winding_gradient_c: float = Field(default=22, gt=0, le=100)
    oil_tau_min: float = Field(default=155, gt=1, le=2000)
    winding_tau_min: float = Field(default=8, gt=0, le=200)
    loss_ratio: float = Field(default=7.5, gt=0, le=100)
    oil_exponent: float = Field(default=.9, gt=.1, le=2)
    winding_exponent: float = Field(default=1.8, gt=.1, le=4)
    hotspot_limit_c: float = Field(default=120, gt=50, le=200)
    oil_limit_c: float = Field(default=100, gt=40, le=160)
    residual_limit_c: float = Field(default=6, gt=0)
    provenance: str = 'Demonstration parameters; not a certified transformer specification.'


class Reading(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    timestamp: datetime
    load_pu: float | None = Field(default=None, ge=0, le=4)
    ambient_c: float | None = Field(default=None, gt=-273.15, le=100)
    oil_c: float | None = Field(default=None, gt=-273.15, le=300)
    oil_reference_c: float | None = Field(default=None, gt=-273.15, le=300)
    voltage_pu: float | None = Field(default=1, gt=0, le=2)
    current_thd_pct: float | None = Field(default=None, ge=0, le=150)

    @field_validator('timestamp')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Timestamp must include a timezone offset or Z.')
        return value


def check_sequence(readings):
    if len(readings) < 2:
        raise ValueError('At least two timestamped readings are required.')
    for left, right in zip(readings, readings[1:]):
        if right.timestamp <= left.timestamp:
            raise ValueError('Timestamps must strictly increase; resolve duplicate or out-of-order messages.')


ASSETS = {
    a.asset_id: a for a in [
        Asset(asset_id='NR-104', name='North industrial feeder', location='Demonstration site A', rated_kva=630),
        Asset(asset_id='NR-207', name='East residential feeder', location='Demonstration site B', rated_kva=400),
        Asset(asset_id='NR-312', name='Campus distribution', location='Demonstration site C', rated_kva=250),
    ]
}
