"""Independent synthetic evaluation plant. Never used as the forecast model."""
import math
import random

SCENARIOS=('healthy','overload','cooling','sensor_bias','dropout','voltage')
MIXED={'overload_sensor_bias':('overload','sensor_bias'),'overload_dropout':('overload','dropout'),
       'voltage_sensor_bias':('voltage','sensor_bias'),'cooling_overload':('cooling','overload')}


FAMILIES=('nonlinear','radiator_lag')


def generate(seed,scenario,minutes=181,*,family='nonlinear',variable_event=False):
    if scenario not in (*SCENARIOS,*MIXED):raise ValueError('Unknown validation scenario')
    if family not in FAMILIES:raise ValueError('Unknown plant family')
    kinds=MIXED.get(scenario,(scenario,))
    rng=random.Random(seed);rise=rng.uniform(45,68);tau=rng.uniform(55,150)
    winding_rise=rng.uniform(20,27);winding_tau=rng.uniform(4,12)
    severity=rng.choice((.2,.5,.8));noise=rng.choice((.15,.5,1.0))
    oil=35.;radiator=35.;winding=8.;rows=[];truth=[]
    event=random.Random(seed+17031).randint(90,115) if variable_event else 100
    for minute in range(minutes):
        load=70+22*math.sin(minute/11) if minute<70 else 85+3*math.sin(minute/15)
        ambient=28+3*math.sin(minute/100);cooling=1.;bias=0.;pu=1.
        active=minute>=event and scenario!='healthy'
        if active and 'overload' in kinds:load=102+severity*60
        if active and 'cooling' in kinds:cooling=1-severity*.85
        if active and 'sensor_bias' in kinds:bias=(2+severity*25)*min(1,(minute-event)/10)
        if active and 'voltage' in kinds:pu=1.05+severity*.25
        target=ambient+rise*(.17*pu**2+.83*(load/100)**2)**.8/cooling
        if minute:
            if family=='nonlinear':
                oil+=(target-oil)*(1-math.exp(-1/tau))-.00008*max(0,oil-ambient)**1.5
            else:
                # Separate radiator storage and oil-to-radiator heat exchange.
                # Forward Euler, one-minute step; not the predictor's one-node ODE.
                loss=(.17*pu**2+.83*(load/100)**2)**.8
                heat=rise*loss/tau
                exchange=(oil-radiator)/(tau*.35)
                rejection=cooling*(radiator-ambient)/(tau*.65)
                oil+=heat-exchange
                radiator+=(exchange-rejection)/.7
            winding+=(winding_rise*(load/100)**1.6-winding)*(1-math.exp(-1/winding_tau))
        oil_m=oil+rng.gauss(0,noise);hot=oil+winding+bias+rng.gauss(0,noise*1.5)
        if active and 'dropout' in kinds and minute%12<8:oil_m=hot=None
        rows.append({'elapsed_s':minute*60,'oil_c':oil_m,'hotspot_c':hot,'ambient_c':ambient,'load_percent':load,'voltage_pu':pu})
        truth.append({'active':active,'hotspot_c':oil+winding,'oil_c':oil})
    return rows,truth,{'scenario':scenario,'event_min':event,'severity':severity,'noise_c':noise,'seed':seed,'family':family}
