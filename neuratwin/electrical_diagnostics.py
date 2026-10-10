"""Observation-only electrical screening and a declared synthetic waveform fixture.

The assessor accepts only cycle measurements and acquisition context, never labels.
No method in this module issues physical commands or claims relay-grade protection.
"""
import math
import numpy as np

VERSION = 'electrical-observer-1'
CLASSES = ('normal', 'overload', 'inrush', 'external_fault', 'suspected_internal_fault', 'sensor_failure', 'ambiguous')
ACTIONS = {
    'normal': 'Continue observing the supplied channels.',
    'overload': 'Compare a thermal load-reduction study and open a load-review work order.',
    'inrush': 'Review energisation evidence; do not infer a validated protection-restraint decision.',
    'external_fault': 'Review simulated fault clearing and upstream/downstream coordination; investigate before recovery.',
    'suspected_internal_fault': 'Escalate simulated isolation and electrical investigation; confirm independent current channels.',
    'sensor_failure': 'Verify the inconsistent or missing channel against an independent reference.',
    'ambiguous': 'Collect independent time-aligned waveform evidence; withhold a specific fault diagnosis.'}


def assess(observations, acquisition):
    rows = [{k:r.get(k) for k in ('time_s','current_pu','voltage_pu','differential_pu','second_harmonic_ratio','valid')}
            for r in observations]  # Explicit allowlist excludes scenario/fault/future metadata.
    out = {'version':VERSION, 'classification':'ambiguous','available':False,'evidence':[],
           'missing':[], 'alternatives':[], 'probability':None, 'detection_delay_s':None,
           'scope':'Synthetic/recorded waveform screening; not field-validated relay protection'}
    if not rows or any(r['valid'] is False or any(not isinstance(r[k],(float,int)) or not math.isfinite(r[k])
            for k in ('time_s','current_pu','voltage_pu')) for r in rows):
        out.update(classification='sensor_failure',available=True,evidence=['Required current/voltage samples are missing or invalid.'])
    else:
        peak = max(r['current_pu'] for r in rows)
        high = [r for r in rows if r['current_pu'] > 2.]
        if not high:
            kind = 'overload' if max(r['current_pu'] for r in rows[-5:]) > 1.05 else 'normal'
            out.update(classification=kind,available=True,evidence=[f'Peak observed current {peak:.2f} pu.'])
        elif not (acquisition.get('sampled_waveform') and acquisition.get('independent_currents') and acquisition.get('time_aligned')
                  and acquisition.get('ratio_phase_compensated') and all(isinstance(r[k],(float,int)) and math.isfinite(r[k]) for r in high for k in ('differential_pu','second_harmonic_ratio'))):
            out['missing']=['Independent, aligned, compensated current waveforms and harmonic features are required.']
            out['alternatives']=['inrush','external_fault','suspected_internal_fault']
        else:
            differential = max(r['differential_pu'] / max(.1,r['current_pu']) for r in high)
            harmonic = float(np.median([r['second_harmonic_ratio'] for r in high]))
            voltage = min(r['voltage_pu'] for r in high)
            early, late = high[0]['current_pu'], rows[-1]['current_pu']
            decay = late / max(.1,early)
            out['evidence']=[f'Peak {peak:.2f} pu; minimum voltage {voltage:.2f} pu.',
                f'Differential/restraint ratio {differential:.2f}; second harmonic {100*harmonic:.1f}%.',
                f'Late/initial high-current ratio {decay:.2f}.']
            if harmonic >= .12 and decay < .65 and voltage > .7:
                kind='inrush'
            elif harmonic >= .10 or acquisition.get('ct_saturation_suspected'):
                kind='ambiguous';out['alternatives']=['inrush','suspected_internal_fault','instrument distortion']
            elif differential < .15 and voltage < .65:
                kind='external_fault'
            elif differential > .3 and voltage < .8 and decay > .7:
                kind='suspected_internal_fault'
            else:
                kind='ambiguous';out['alternatives']=['inrush','fault','instrumentation problem']
            out.update(classification=kind,available=kind!='ambiguous')
    out['action']=ACTIONS[out['classification']]
    out['abstained']=out['classification']=='ambiguous'
    return out


def generate(seed, kind):
    """Whole independent events, with harmonics computed from sampled signals."""
    rng=np.random.default_rng(seed); frequency=float(rng.choice([50.,60.])); n=128; cycles=30
    phase=np.arange(n)*2*np.pi/n; onset=5/frequency; rows=[]; waveform=[]
    severity=float(rng.uniform(3.,7.)); noise=float(rng.uniform(.002,.025))
    for cycle in range(cycles):
        after=cycle>=5; amp=float(rng.uniform(.6,.85)); v=1.; differential=0.; h2=0.
        if after:
            if kind=='overload':amp=float(rng.uniform(1.2,1.65))
            elif kind in ('external_fault','suspected_internal_fault','ambiguous'):amp=severity;v=float(rng.uniform(.25,.55))
            elif kind=='inrush':amp=.7+severity*np.exp(-(cycle-5)/7);h2=float(rng.uniform(.18,.3));v=.9
            if kind=='suspected_internal_fault':differential=.65
            if kind=='inrush':differential=.75
            if kind=='ambiguous':differential=.6;h2=.22
        primary=np.sqrt(2)*amp*(np.sin(phase)+h2*np.sin(2*phase))+rng.normal(0,noise,n)
        secondary=np.sqrt(2)*amp*(1-differential)*np.sin(phase)+rng.normal(0,noise,n)
        voltage=np.sqrt(2)*v*np.sin(phase)+rng.normal(0,noise,n)
        valid=not(kind=='sensor_failure' and cycle>=5)
        f=np.fft.rfft(primary);fund=max(1e-9,abs(f[1]))
        rows.append({'time_s':cycle/frequency,'current_pu':float(np.sqrt(np.mean(primary**2))) if valid else None,
            'voltage_pu':float(np.sqrt(np.mean(voltage**2))),
            'differential_pu':float(np.sqrt(np.mean((primary-secondary)**2))) if valid else None,
            'second_harmonic_ratio':float(abs(f[2])/fund) if valid else None,'valid':valid})
        if 5<=cycle<9:
            waveform.extend({'time_s':(cycle+i/n)/frequency,'primary_pu':float(primary[i]),
                'secondary_compensated_pu':float(secondary[i]),'voltage_pu':float(voltage[i])} for i in range(n))
    acquisition={'source':'synthetic waveform fixture','sampled_waveform':True,'independent_currents':True,
        'time_aligned':True,'ratio_phase_compensated':True,'frequency_hz':frequency,'samples_per_cycle':n,
        'basis':'Per-unit currents on a common rated secondary base; ideal ratio/phase compensation',
        'ct_saturation_suspected':False}
    return rows, acquisition, {'label':kind,'seed':seed,'onset_s':onset,'waveforms':waveform}


def evaluate(seeds=range(1000,1020)):
    cases=[]
    for seed in seeds:
        for kind in CLASSES:
            rows,context,truth=generate(seed,kind);result=assess(rows,context)
            delay=None
            if kind not in ('normal','ambiguous'):
                for i in range(6,len(rows)+1):
                    if assess(rows[:i],context)['classification']==kind:
                        delay=max(0,rows[i-1]['time_s']-truth['onset_s']);break
            cases.append({'seed':seed,'truth':kind,'predicted':result['classification'],'delay_s':delay,
                'baseline':'overload' if any((r['current_pu'] or 0)>1.05 for r in rows) else 'normal'})
    confusion={k:{p:sum(c['truth']==k and c['predicted']==p for c in cases) for p in CLASSES} for k in CLASSES}
    metrics={}
    for kind in CLASSES:
        tp=confusion[kind][kind];actual=sum(c['truth']==kind for c in cases);predicted=sum(c['predicted']==kind for c in cases)
        metrics[kind]={'count':actual,'precision':tp/predicted if predicted else None,'recall':tp/actual if actual else None}
    normals=[c for c in cases if c['truth']=='normal']
    return {'version':VERSION,'source':'Independent synthetic event seeds; no field validation or calibrated probabilities',
        'split':'Entire events held out by seed; no adjacent-window train/test split; rules are fixed, not fitted to this evaluation',
        'count':len(cases),'confusion_matrix':confusion,'classes':metrics,
        'coverage':sum(c['predicted']!='ambiguous' for c in cases)/len(cases),
        'false_alarm_events':sum(c['predicted'] not in ('normal','ambiguous') for c in normals),'normal_event_denominator':len(normals),
        'accuracy':sum(c['truth']==c['predicted'] for c in cases)/len(cases),
        'baseline_accuracy':sum(c['truth']==c['baseline'] for c in cases)/len(cases),
        'limitations':['Synthetic generator and deterministic observer are not independent physical validation.',
            'Low-harmonic inrush, CT saturation and overlapping faults can be ambiguous; robustness is not established.'], 'cases':cases}
