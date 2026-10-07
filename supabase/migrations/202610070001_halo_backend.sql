-- NeuraTwin Halo: additive schema, private evidence, atomic writes.
-- Apply as project database owner. Client keys deliberately have no table access.
begin;
create table if not exists public.halo_records (
  kind text not null, id text not null, content jsonb not null,
  revision bigint not null default 1, updated_at timestamptz not null default now(),
  primary key (kind, id)
);
create index if not exists halo_records_kind_updated on public.halo_records(kind, updated_at desc);
create table if not exists public.halo_frames (
  id bigint generated always as identity primary key,
  device_id text not null, boot_id text not null, sequence bigint not null check(sequence >= 0),
  timestamp timestamptz not null, received_at timestamptz not null default now(), content jsonb not null,
  unique(device_id, boot_id, sequence)
);
create index if not exists halo_frames_device_id on public.halo_frames(device_id, id desc);
create table if not exists public.halo_events (
  id uuid primary key, asset_id text not null, kind text not null, content jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists halo_events_asset_time on public.halo_events(asset_id, created_at desc);
create table if not exists public.halo_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null check(role in ('viewer','operator','admin')), active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.halo_records enable row level security;
alter table public.halo_frames enable row level security;
alter table public.halo_events enable row level security;
alter table public.halo_members enable row level security;
revoke all on public.halo_records, public.halo_frames, public.halo_events, public.halo_members from anon, authenticated;
grant all on public.halo_records, public.halo_frames, public.halo_events, public.halo_members to service_role;
grant usage, select on sequence public.halo_frames_id_seq to service_role;

-- A request commits its record changes and audit events together. Expected
-- revisions also protect read dependencies across multiple application workers.
create or replace function public.halo_commit(p_reads jsonb, p_records jsonb, p_events jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare r jsonb; actual bigint;
begin
  perform pg_advisory_xact_lock(7421090001);
  for r in select value from jsonb_array_elements(p_reads) loop
    select revision into actual from public.halo_records where kind=r->>'kind' and id=r->>'id';
    if actual is distinct from (r->>'revision')::bigint then
      raise sqlstate 'PT409' using message='Record changed concurrently. Refresh and retry.';
    end if;
  end loop;
  for r in select value from jsonb_array_elements(p_records) loop
    insert into public.halo_records(kind,id,content) values(r->>'kind',r->>'id',r->'content')
    on conflict(kind,id) do update set content=excluded.content,
      revision=public.halo_records.revision+1, updated_at=now();
  end loop;
  for r in select value from jsonb_array_elements(p_events) loop
    insert into public.halo_events(id,asset_id,kind,content,created_at)
    values((r->>'id')::uuid,r->>'asset_id',r->>'kind',r->'content',(r->>'created_at')::timestamptz);
  end loop;
  return jsonb_build_object('committed',true);
end $$;

create or replace function public.halo_ingest_frame(p_frame jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare old jsonb; latest timestamptz; frame_id bigint; acquired timestamptz;
begin
  perform pg_advisory_xact_lock(hashtextextended('halo-device:'||(p_frame->>'device_id'),0));
  acquired := (p_frame->>'timestamp')::timestamptz;
  if acquired > now() + interval '5 seconds' then
    raise sqlstate 'PT422' using message='Future acquisition timestamp rejected.';
  end if;
  select content into old from public.halo_frames where device_id=p_frame->>'device_id'
    and boot_id=p_frame->>'boot_id' and sequence=(p_frame->>'sequence')::bigint;
  if found then
    if old <> p_frame then raise sqlstate 'PT409' using message='Sequence reused with different content.'; end if;
    return jsonb_build_object('accepted',true,'duplicate',true,'sequence',p_frame->'sequence');
  end if;
  select content into old from public.halo_frames where device_id=p_frame->>'device_id'
    and boot_id=p_frame->>'boot_id' order by sequence desc limit 1;
  if found and ((p_frame->>'sequence')::bigint <= (old->>'sequence')::bigint
    or (p_frame->>'uptime_ms')::bigint <= (old->>'uptime_ms')::bigint
    or acquired <= (old->>'timestamp')::timestamptz) then
    raise sqlstate 'PT409' using message='Out-of-order telemetry rejected.';
  end if;
  select timestamp into latest from public.halo_frames where device_id=p_frame->>'device_id' order by id desc limit 1;
  if found and acquired <= latest then raise sqlstate 'PT409' using message='Old session cannot overwrite live state.'; end if;
  insert into public.halo_frames(device_id,boot_id,sequence,timestamp,content)
    values(p_frame->>'device_id',p_frame->>'boot_id',(p_frame->>'sequence')::bigint,acquired,p_frame)
    returning id into frame_id;
  return jsonb_build_object('accepted',true,'duplicate',false,'sequence',p_frame->'sequence','evidence_id','T-'||frame_id);
end $$;

create or replace function public.halo_health()
returns jsonb language sql security definer set search_path = '' as $$
  select jsonb_build_object('schema_version',1,'database','connected','storage','private');
$$;
revoke all on function public.halo_commit(jsonb,jsonb,jsonb) from public,anon,authenticated;
revoke all on function public.halo_ingest_frame(jsonb) from public,anon,authenticated;
revoke all on function public.halo_health() from public,anon,authenticated;
grant execute on function public.halo_commit(jsonb,jsonb,jsonb) to service_role;
grant execute on function public.halo_ingest_frame(jsonb) to service_role;
grant execute on function public.halo_health() to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('halo-evidence','halo-evidence',false,4000000,array['image/jpeg','image/png'])
on conflict(id) do nothing;
notify pgrst, 'reload schema';
commit;
