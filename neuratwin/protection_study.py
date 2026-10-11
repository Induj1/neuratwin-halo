"""RMS screening and explicitly synthetic fault exercises. No hardware commands."""
import math
from datetime import datetime
from .prototype_physics import capacity, oil_target


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def electrical(rows,settings,*,rated_current=1,nominal_voltage=12,live=False,scenario=None):
    synthetic=bool(scenario and scenario['kind']!='none')
    scope='RMS screening only; cannot discriminate inrush or locate a fault; not fast physical protection.'
    if synthetic:
        elapsed=scenario['elapsed_seconds'];kind=scenario['kind']
        fault_time=max(4.,settings.startup_guard_s+.5)
        pickup=(scenario['current_pu']>=settings.fault_pickup_pu and .2<=settings.voltage_dip_pu) if kind=='short' else 1.5>=settings.overload_pickup_pu
        trip_time=fault_time+(max(.25,settings.fault_delay_s) if kind=='short' else settings.overload_delay_s+1) if pickup and kind!='recovery' else math.inf
        end=max(0,min(elapsed,trip_time+8,120))
        times=sorted({0.,end,*[v/20 for v in range(int(end*20)+1)],fault_time if end>=fault_time else end,trip_time if end>=trip_time else end})
        data=[]
        for t in times:
            current=(scenario['current_pu'] if kind=='short' else 1.5)*rated_current if t>=fault_time and kind!='recovery' else .65*rated_current
            voltage=nominal_voltage*(.2 if kind=='short' and t>=fault_time else 1)
            if t>=trip_time:current=0.;voltage=0.
            data.append(dict(seconds=t,current_a=current,voltage_v=voltage,valid=True))
        stage='normal' if kind=='recovery' else 'isolated' if elapsed>=trip_time else 'suspected_short' if kind=='short' and pickup and elapsed>=fault_time else 'overload' if elapsed>=fault_time+settings.overload_delay_s and pickup else 'watch' if elapsed>=fault_time else 'normal'
        origin='Simulated fault exercise'
    else:
        unique={r.get('sample_key',r.get('timestamp')):r for r in rows if r.get('timestamp')}
        records=sorted(unique.values(),key=lambda r:r['timestamp'])
        data=[];first=None
        for r in records:
            at=datetime.fromisoformat(r['timestamp'].replace('Z','+00:00')).timestamp()
            if first is None:first=at
            measured=r.get('observed_current_a',r.get('current_a'))
            source=r.get('current_source','')
            qualified=source=='industrial simulation' or (r.get('calibrated') and r.get('observed_current_source')=='measured')
            valid=bool(qualified and finite(measured) and measured>=0 and finite(r.get('voltage_v')))
            data.append(dict(seconds=at-first,current_a=measured,voltage_v=r.get('voltage_v'),valid=valid,boot_id=r.get('boot_id')))
        stage='unavailable';origin='Measured RMS screening' if not records or records[-1].get('current_source')!='industrial simulation' else 'Industrial simulation'
    exposure=0.;coverage=0.;over_duration=0.;short_duration=0.;previous=None;peak=0.;trace=[];detected='normal';boot_start=0.
    for r in data:
        dt=r['seconds']-previous['seconds'] if previous else 0
        connected=bool(previous and r['valid'] and previous['valid'] and 0<dt<=(65 if origin=='Industrial simulation' else 10) and previous.get('boot_id')==r.get('boot_id'))
        if r['valid']:
            peak=max(peak,r['current_a']);k=r['current_a']/rated_current;v=r['voltage_v']/nominal_voltage
            old_k=previous['current_a']/rated_current if connected else 0
            if connected:
                exposure+=(previous['current_a']**2+r['current_a']**2)*dt/2;coverage+=dt
            if previous and previous.get('boot_id')!=r.get('boot_id'):boot_start=r['seconds']
            over=k>=settings.overload_pickup_pu or detected=='overload' and k>settings.overload_pickup_pu-.05
            guard=r['seconds']-boot_start<settings.startup_guard_s
            short=not guard and k>=settings.fault_pickup_pu and v<=settings.voltage_dip_pu
            retained=detected=='suspected_short' and connected and not guard and k>settings.fault_pickup_pu*.9
            over_duration=over_duration+dt if connected and over and old_k>settings.overload_pickup_pu-.05 else 0
            short_duration=short_duration+dt if connected and short and old_k>=settings.fault_pickup_pu and previous['voltage_v']/nominal_voltage<=settings.voltage_dip_pu else 0
            detected='suspected_short' if retained or short and short_duration>=settings.fault_delay_s else 'overload' if over and over_duration>=settings.overload_delay_s else 'watch' if over else 'normal'
        else:over_duration=short_duration=0;detected='unavailable'
        trace.append({**r,'i2t_a2s':exposure,'gap_before':bool(previous and not connected)})
        previous=r
    if not synthetic:stage=detected if live and data and data[-1]['valid'] else 'unavailable'
    last=data[-1] if data else {}
    labels={'normal':'Within configured limits','watch':'Overcurrent observed','overload':'Sustained overload','suspected_short':'Suspected short circuit','isolated':'Simulated isolation','unavailable':'Current detection unavailable'}
    severity='critical' if stage in ('suspected_short','isolated') else 'warning' if stage in ('overload','watch') else 'normal' if stage=='normal' else 'unavailable'
    return dict(available=stage!='unavailable',stage=stage,severity=severity,label=labels[stage],source=origin,simulated=synthetic,
        current_a=last.get('current_a') if stage!='unavailable' else None,voltage_v=last.get('voltage_v') if stage!='unavailable' else None,
        rated_current_a=rated_current,nominal_voltage_v=nominal_voltage,peak_a=peak if any(r['valid'] for r in data) else None,i2t_a2s=exposure if any(r['valid'] for r in data) else None,covered_seconds=coverage,
        overload_seconds=over_duration,trace=trace,scope=scope,
        reason='Independent calibrated current is required; resistor-bank estimates cannot detect a short circuit.' if stage=='unavailable' else scope,
        recommendation='Inspect the simulated fault and record corrective action.' if synthetic and severity=='critical' else 'Investigate and isolate under the site procedure.' if severity=='critical' else 'Reduce demand and inspect the load.' if severity=='warning' else 'Continue monitoring.' if stage=='normal' else 'Check the current sensor and calibration.',
        protection_action='Simulated only; no ESP32 command' if synthetic else 'Advisory only; no automatic switching',
        assumed_impedance_percent=settings.impedance_percent,
        prospective_fault_a=rated_current*100/settings.impedance_percent if settings.impedance_percent else None)


def calculations(result,p,electrical_result):
    """Same inputs as the assessment; plain-text equations also render in PDFs."""
    k=result.get('loading_pu');current=result.get('input_current_a');inventory=result.get('inventory_l')
    def fmt(v):return f'{v:.4g}' if finite(v) else 'unavailable'
    cards=[]
    def add(title,equation,substitution,unit,basis):cards.append(dict(title=title,equation=equation,substitution=substitution,unit=unit,basis=basis))
    add('Loading and copper heating','K = I / I_rated; loading = 100 K; P_cu = I^2 R_w',
        f'I = {fmt(current)} A; rated = {fmt(electrical_result["rated_current_a"])} A; loading = {fmt(k*100 if k is not None else None)}%; copper-loss multiplier = {fmt(k*k if k is not None else None)}; copper loss = {fmt(current**2*p.winding_resistance_ohm if current is not None and p.winding_resistance_ohm else None)} W',
        'A, %, W',f'Current basis: {result.get("current_source","unavailable")}. Winding resistance is entered, not inferred; constant-resistance multiplier.')
    add('Overcurrent exposure','J = integral I(t)^2 dt',f'J = {fmt(electrical_result["i2t_a2s"])} A^2 s across {fmt(electrical_result["covered_seconds"])} s of valid intervals','A^2 s',electrical_result['source']+'. Sampled trapezoidal integration; gaps excluded; not protection-grade let-through energy.')
    add('Prospective fault current','I_sc = I_rated * 100 / Z_percent',f'Z = {fmt(p.impedance_percent)}%; I_sc = {fmt(electrical_result["prospective_fault_a"])} A','A','Requires declared transformer impedance. Infinite-source terminal approximation; upstream impedance excluded. Not a detected fault.')
    add('Oil mass balance','V = V_0 - integral q_loss dt + V_refill; remaining = 100 V / V_0',
        f'Initial {fmt(p.oil_litres)} L; remaining {fmt(inventory)} L; loss {fmt(result.get("oil_balance",{}).get("lost_total_l"))} L; refill {fmt(result.get("oil_balance",{}).get("refilled_total_l"))} L; remaining {fmt(result.get("inventory_percent"))}%',
        'L at 25 C, %','Declared simulated inventory; no measured oil-level channel. Loss is not attributed to evaporation.')
    add('Time to low-oil limit','t_limit = max(0, (V - V_limit) / q_loss)',
        f'({fmt(inventory)} - {fmt(result.get("oil_limit_l"))}) L / {fmt(result.get("loss_rate_l_min"))} L/min = {fmt(result.get("oil_time_to_limit_min"))} model min',
        'model min','Conditional on a constant positive leak rate. Already at/below the limit gives zero; above the limit with zero loss has no finite crossing.')
    add('Thermal expansion','V(T) = V_ref [1 + beta (T_bulk - 25)]',
        f'{fmt(inventory)} L; beta = {fmt(p.expansion_per_c)} /C; bulk = {fmt(result.get("bulk_oil_c"))} C; volume = {fmt(result.get("expanded_volume_l"))} L',
        'L','Assumed oil coefficient; bulk rise = 0.8 * top-oil rise. Expansion changes volume, not oil mass.')
    c=capacity(p,inventory) if inventory is not None else None;ua=capacity(p)*1000/(60*p.oil_tau_min)
    target=oil_target(k,p) if k is not None else None
    if result.get('energized') is False:target=p.ambient_c
    add('Thermal capacity and energy balance','C = C_solid + rho V c_p; C dT/dt = P_loss - UA(T - T_ambient)',
        f'C = {fmt(p.solid_capacity_kj_k)} + {fmt(p.oil_density_kg_l)} * {fmt(inventory)} * {fmt(p.oil_cp_kj_kg_k)} = {fmt(c)} kJ/K; UA = {fmt(ua)} W/K; equivalent P_loss = {fmt(ua*(target-p.ambient_c) if target is not None else None)} W',
        'kJ/K, W/K, W','Assumed lumped capacity. UA calibrated to declared full-inventory time constant; equivalent heat input matches the thermal target, not measured electrical loss. Oil loss alone does not change steady-state target.')
    add('Conditional top-oil forecast','T_inf = T_ambient + rise_rated [(1 + R K^2)/(1 + R)]^0.8 / cooling; T(t) = T_inf + (T_0 - T_inf) exp(-t/tau)',
        f'T_inf = {fmt(target)} C; present = {fmt(result.get("oil_c"))} C; effective tau = {fmt(result.get("effective_tau_min"))} min',
        'C, model min','Simplified loading model. Forecast steps update capacity as oil is lost; parameters are assumptions. Surface probe is an initial proxy, not oil temperature.')
    add('Sealed gas-cushion pressure','P_abs = P_0 (T_K/T_0K) V_gas0/V_gas; P_gauge = P_abs - P_0',
        f'Initial gas = {fmt(p.gas_litres)} L; current gas = {fmt(result.get("gas_volume_l"))} L; pressure = {fmt(result.get("pressure_kpa"))} kPa gauge',
        'K, L, kPa','Rigid sealed tank with fixed gas mass; leak assumed not to admit air. Not valid for a vented conservator, ruptured tank or arc pressure.')
    f=result.get('fem',{})
    add('Finite-element heat balance','-div(k grad T) = q_volume; -k grad T . n = h(T - T_ambient)',
        f'Heat in = {fmt(f.get("heat_input_w"))} W; rejected = {fmt(f.get("heat_rejected_w"))} W; residual = {fmt(f.get("balance_error_w"))} W',
        'W, C','Separate illustrative 2D steady conduction model; declared geometry and materials, no measured internal temperature or oil-flow simulation.')
    return cards
