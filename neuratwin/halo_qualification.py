"""Past-only checks of the active model; no fitting, switching or score selection."""
from copy import deepcopy
from datetime import timedelta
from . import halo_engine as engine


def qualify(snap, horizon):
    from .halo_evidence import predict, score_prediction, model_ready
    dt='transformer' in snap
    result={'status':'unavailable','recommendations_allowed':False,'horizon_min':horizon,
            'model_id':(snap.get('model') or {}).get('id','distribution-loading-model'),
            'asset_id':snap['asset_id'],'source':snap['source'],'windows':[],
            'policy':'Up to three non-overlapping completed windows at the requested horizon. At least 80% coverage and 80% unchanged-input samples, with at least three samples per window. All three must beat persistence by at least 5% for bench qualification. This is a prototype screening policy, not field certification.'}
    row=snap.get('current') or {}
    if not row:
        return {**result,'reason':'No observed starting state.'}
    if not dt:
        reason=model_ready(snap)
        if reason:return {**result,'reason':reason}
    elif row.get('confidence')=='Low':
        return {**result,'reason':'Resolve low-confidence study inputs first.'}
    history=snap['history']; end=engine.timestamp(row['timestamp']); span=timedelta(minutes=horizon)
    # Backwards windows share no target samples. The origin is known before its future.
    for _ in range(3):
        candidates=[(i,r) for i,r in enumerate(history) if engine.timestamp(r['timestamp'])<=end-span]
        if not candidates:break
        index,origin=candidates[-1]
        prefix=history[:index+1]
        sample=deepcopy(snap);sample['current']=origin;sample['history']=prefix;sample['connection']='replay'
        try:
            prediction=predict(sample,horizon);prediction['horizon_min']=horizon
        except (ValueError,KeyError) as exc:
            result['windows'].append({'origin':origin['timestamp'],'eligible':False,'reason':str(exc)})
            end=engine.timestamp(origin['timestamp']);continue
        score=score_prediction(prediction,[r for r in history if engine.timestamp(r['timestamp'])<=end])
        held=score['assumptions_held']; count=held['count']; expected=max(1,horizon*60/prediction['cadence_seconds'])
        coverage=score['all_observations']['count']/expected
        unchanged=count/max(1,score['all_observations']['count'])
        eligible=score['status']=='complete' and coverage>=.8 and unchanged>=.8 and count>=3 and not score['gaps'] and not score['missing_samples']
        beats=eligible and held['mae_c']<held['persistence_mae_c']*.95
        result['windows'].append({'origin':origin['timestamp'],'end':score['expected_end_at'],'eligible':eligible,
                                  'reason':'Completed comparable window.' if eligible else 'Insufficient comparable coverage, changed inputs, missing readings or gaps.',
                                  'count':count,'coverage':min(1,coverage),'mae_c':held['mae_c'],'persistence_mae_c':held['persistence_mae_c'],
                                  'beats_persistence':bool(beats)})
        end=engine.timestamp(origin['timestamp'])
    eligible=[w for w in result['windows'] if w['eligible']]
    # A poor latest comparable window cannot be hidden by older, better windows.
    latest=result['windows'][0] if result['windows'] else None
    degraded=bool(latest and latest['eligible'] and not latest['beats_persistence'])
    qualified=len(eligible)==3 and all(w['beats_persistence'] for w in eligible)
    result['status']='degraded' if degraded else 'qualified' if qualified else 'insufficient evidence'
    result['reason']=('Latest comparable window does not beat persistence by 5%. Intervention recommendations are withheld.' if degraded else
                      'Three completed windows beat persistence by at least 5%.' if qualified else
                      'Three recent comparable completed windows have not qualified this horizon. Continue recording or review the reference model.')
    if not dt and qualified:
        model=snap['model']
        within=all(model[a][0]<=row[k]<=model[a][1] for a,k in [('current_range_a','current_a'),('ambient_range_c','ambient_c')])
        if not within or horizon*60>model['validation_span_s']:
            result['status']='outside validated range';result['reason']='Current inputs or forecast horizon exceed reference validation. Intervention recommendations are withheld.'
    result['recommendations_allowed']=result['status']=='qualified'
    if dt:
        # Oil verification cannot qualify an unmeasured winding hot-spot intervention.
        result['recommendations_allowed']=False
        result['scope']='Oil forecast screening only. Winding hot-spot and interventions remain model-study scenarios.'
        result['study_comparison_allowed']=not degraded
    else:
        result['scope']='Surface forecasting on this asset/source/calibration; no oil, winding or remaining-life qualification.'
        result['study_comparison_allowed']=result['recommendations_allowed']
    return result
