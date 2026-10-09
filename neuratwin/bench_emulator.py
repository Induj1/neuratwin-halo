"""Deterministic, software-only acquisition fixture; never a physical device.

Two thermal nodes drive synthetic surface measurements. This exercises the
workflow, not the independent industrial benchmark or electrical hardware.
"""
from datetime import datetime, timedelta, timezone
import math

CALIBRATION={'id':'EMULATOR-CAL','secondary_v_per_mv':.02,'current_a_per_mv':.002,
             'current_noise_mv':2.,'surface_offset_c':.2,'surface_reference':'Software fixture only',
             'ambient_reference':'Software fixture only'}


def new():
    return {'version':'bench-emulator-1','index':-1,'core_c':30.,'surface_c':29.,'branches':1}


def step(state,training=False):
    state['index']+=1;i=state['index']
    branches=(1 if i<80 else 2 if i<140 else 3) if training else state['branches']
    state['branches']=branches
    voltage=12.2-.06*branches;current=branches*voltage/39;ambient=28.
    state['core_c']+=(ambient+9+23*current**2-state['core_c'])/90
    state['surface_c']+=(state['core_c']-2-state['surface_c'])/55
    surface=state['surface_c']+.015*math.sin(i*1.73)
    timestamp=(datetime(2026,10,8,9,tzinfo=timezone.utc)+timedelta(seconds=i*5)).isoformat()
    rms=math.sqrt((current/.002)**2+4);voltage_rms=voltage/.02
    raw={'secondary_rms_mv':voltage_rms,'secondary_bias_mv':1300.,'secondary_min_mv':1300-math.sqrt(2)*voltage_rms,'secondary_max_mv':1300+math.sqrt(2)*voltage_rms,
         'current_rms_mv':rms,'current_bias_mv':1305.,'current_min_mv':1305-math.sqrt(2)*rms,'current_max_mv':1305+math.sqrt(2)*rms,
         'surface_raw_c':surface-.2,'sample_count':400,'window_us':200000.}
    return {'device_id':'EMULATOR','boot_id':'software-fixture','sequence':i,'uptime_ms':i*5000,
            'timestamp':timestamp,'secondary_v':voltage,'current_a':current,'surface_c':surface,
            'ambient_c':ambient,'ambient_source':'probe','primary_v':None,'primary_current_a':None,
            'relay_states':[j<branches for j in range(4)],'relay_output_configured':False,
            'quality_flags':[],'calibration_id':CALIBRATION['id'],'raw':raw,'evidence_id':f'EMU-{i}',
            'source':'software_emulator'}


def initial():
    state=new();rows=[step(state,training=True) for _ in range(241)]
    return state,rows
