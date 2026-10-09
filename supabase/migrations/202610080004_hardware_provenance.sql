-- Additive. Apply as project owner after 202610070002. Never assigns a config
-- identity to an older frame: absent configuration remains explicitly unbound.
begin;

create or replace function public.halo_enqueue_analysis()
returns trigger language plpgsql security definer set search_path = '' as $$
declare job_id text;
begin
  -- Share the record-UOW lock so kind-revision reads and job creation cannot race.
  perform pg_advisory_xact_lock(7421090001);
  job_id := 'analysis:'||new.device_id||'/'||new.boot_id||'/'||new.sequence;
  insert into public.halo_records(kind,id,content)
    values('analysis_job',job_id,jsonb_build_object('id',job_id,'frame',new.content,
      'config_id',new.content->'config_id','status','pending','created_at',new.received_at,
      'admission','atomic acquisition'));
  insert into public.halo_kind_revisions(kind,revision) values('analysis_job',1)
    on conflict(kind) do update set revision=public.halo_kind_revisions.revision+1;
  return new;
end $$;

drop trigger if exists halo_frame_analysis_pending on public.halo_frames;
create trigger halo_frame_analysis_pending after insert on public.halo_frames
  for each row execute function public.halo_enqueue_analysis();

-- Recover only each device's most recent historical acquisition. Older history
-- remains intact; retry of an older frame can create an explicit legacy job.
insert into public.halo_records(kind,id,content)
select 'analysis_job','analysis:'||f.device_id||'/'||f.boot_id||'/'||f.sequence,
  jsonb_build_object('id','analysis:'||f.device_id||'/'||f.boot_id||'/'||f.sequence,
    'frame',f.content,'config_id',f.content->'config_id','status','pending',
    'created_at',f.received_at,'admission','legacy migration')
from (select distinct on(device_id) * from public.halo_frames order by device_id,id desc) f
on conflict(kind,id) do nothing;
insert into public.halo_kind_revisions(kind,revision) values('analysis_job',1)
  on conflict(kind) do update set revision=public.halo_kind_revisions.revision+1;

create or replace function public.halo_hardware_health()
returns jsonb language sql security definer set search_path = '' as $$
  select jsonb_build_object('hardware_schema_version',1,'durable_analysis',
    exists(select 1 from pg_catalog.pg_trigger t where t.tgrelid='public.halo_frames'::regclass
      and t.tgname='halo_frame_analysis_pending' and t.tgenabled in ('O','A')));
$$;
revoke all on function public.halo_enqueue_analysis() from public,anon,authenticated;
revoke all on function public.halo_hardware_health() from public,anon,authenticated;
grant execute on function public.halo_hardware_health() to service_role;
notify pgrst,'reload schema';
commit;
