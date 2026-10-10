"""Declared three-phase terminal fault model; never used by the physical bench."""
import math

VERSION = 'terminal-fault-rms-1'


def terminal_fault(settings, voltage_pu=1.):
    kva, voltage = settings['rated_kva'], settings['secondary_v']
    rated = kva * 1000 / (math.sqrt(3) * voltage)
    base_ohms = voltage ** 2 / (kva * 1000)
    impedances = []
    for prefix, default, xr in [('transformer', 5., 5.), ('source', 0., 10.), ('cable', 0., 1.)]:
        key = 'impedance_percent' if prefix == 'transformer' else prefix + '_impedance_percent'
        percent = settings.get(key, default)
        ratio = settings.get(prefix + '_xr', xr)
        if not math.isfinite(percent) or percent < 0 or (prefix == 'transformer' and percent == 0):
            raise ValueError('Transformer impedance must be positive; source/cable impedances nonnegative.')
        if not math.isfinite(ratio) or ratio < 0:
            raise ValueError('X/R ratios must be finite and nonnegative.')
        r = percent / 100 / math.sqrt(1 + ratio * ratio)
        impedances.append(complex(r, r * ratio))
    total = sum(impedances)
    amps = rated * voltage_pu / abs(total)
    return {'version': VERSION, 'rated_secondary_a': rated, 'prospective_rms_a': amps,
            'fault_multiple': amps / rated, 'total_impedance_pu': abs(total),
            'base_ohms': base_ohms, 'r_ohms': total.real * base_ohms, 'x_ohms': total.imag * base_ohms,
            'frequency_hz': settings.get('frequency_hz', 50),
            'transformer_impedance_percent': settings.get('impedance_percent', 5.),
            'source_impedance_percent': settings.get('source_impedance_percent', 0.),
            'cable_impedance_percent': settings.get('cable_impedance_percent', 0.),
            'voltage_pu': voltage_pu, 'basis': 'All impedances on transformer rated kVA / secondary line-line voltage base',
            'scope': 'Balanced three-phase bolted fault at cable end; zero cable impedance means secondary terminals',
            'assumptions': 'Symmetrical RMS only; no DC offset, peak making current, CT saturation or withstand model. Zero source impedance is a stiff source.',
            'provenance': 'Selected run profile; default values are illustrative, not bench measurements'}


def pressure_signal(state):
    """Explicit scripted tank gas-space scenario, not an oil/gas physical model."""
    fault = state.get('fault')
    active = fault and fault['kind'] in ('pressure', 'pressure_sensor') and state['elapsed_s'] < fault['until_s']
    if active and fault['kind'] == 'pressure_sensor':
        return {'pressure_kpa': None, 'pressure_rate_kpa_s': None, 'pressure_quality': 'unavailable'}
    if not active:
        return {'pressure_kpa': 5., 'pressure_rate_kpa_s': 0., 'pressure_quality': 'simulated'}
    elapsed = max(0., state['elapsed_s'] - fault.get('started_s', state['elapsed_s']))
    rate = 2. * fault['severity']
    value = min(100., 5. + elapsed * rate)
    return {'pressure_kpa': value, 'pressure_rate_kpa_s': rate if value < 100 else 0., 'pressure_quality': 'simulated'}


PRESSURE_MODEL = {'version': 'tank-pressure-scenario-1', 'unit': 'kPa gauge',
    'location': 'Illustrative sealed oil-filled tank gas space', 'source': 'scripted industrial scenario',
    'cadence_s': 5, 'filter': 'None; deterministic scenario samples',
    'limitations': 'Not a rupture model or confirmed internal-fault diagnosis. Detection does not perform pressure relief.'}
