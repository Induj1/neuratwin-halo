"""Fleet atomic publication through the existing Supabase optimistic transaction adapter."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from test_cloud import backend
from neuratwin import fleet_api, cloud, halo_store as store

USER=dict(user_id='test-reviewer',role='admin',mode='test')


def test_cloud_tick_conflict_publishes_no_partial_fleet(backend):
    run=fleet_api.create(fleet_api.Create(request_id=str(uuid4())),USER)
    one=cloud.UnitOfWork();two=cloud.UnitOfWork()
    payload=fleet_api.Tick(request_id=str(uuid4()),revision=0,minutes=5)
    token=cloud.current.set(one)
    try:first=fleet_api.tick(run['id'],payload,USER)
    finally:cloud.current.reset(token)
    token=cloud.current.set(two)
    try:second=fleet_api.tick(run['id'],fleet_api.Tick(request_id=str(uuid4()),revision=0,minutes=30),USER)
    finally:cloud.current.reset(token)
    assert first['minute']==5 and second['minute']==30
    one.commit()
    with pytest.raises(HTTPException) as error:two.commit()
    assert error.value.status_code==409
    saved=store.get('fleet_run',run['id']);assert saved['minute']==5 and saved['revision']==1
    assert store.get('fleet_tick',run['id']+':1')['rows'][-1]['minute']==5
    again=fleet_api.tick(run['id'],payload,USER)
    assert again==first
