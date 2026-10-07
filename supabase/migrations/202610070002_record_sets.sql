-- Protect predicates (for example "no unresolved incident exists") as well as
-- individual records, preventing concurrent inserts from bypassing CAS checks.
begin;
create table if not exists public.halo_kind_revisions(kind text primary key, revision bigint not null default 0);
alter table public.halo_kind_revisions enable row level security;
revoke all on public.halo_kind_revisions from anon,authenticated;
grant all on public.halo_kind_revisions to service_role;
create or replace function public.halo_commit(p_reads jsonb,p_records jsonb,p_events jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare r jsonb; actual bigint; changed_kind text;
begin
  perform pg_advisory_xact_lock(7421090001);
  for r in select value from jsonb_array_elements(p_reads) loop
    if r->>'id' is null then
      select revision into actual from public.halo_kind_revisions where kind=r->>'kind';
      actual:=coalesce(actual,0);
    else
      select revision into actual from public.halo_records where kind=r->>'kind' and id=r->>'id';
    end if;
    if actual is distinct from (r->>'revision')::bigint then
      raise sqlstate 'PT409' using message='Record changed concurrently. Refresh and retry.';
    end if;
  end loop;
  for r in select value from jsonb_array_elements(p_records) loop
    insert into public.halo_records(kind,id,content) values(r->>'kind',r->>'id',r->'content')
    on conflict(kind,id) do update set content=excluded.content,revision=public.halo_records.revision+1,updated_at=now();
  end loop;
  for changed_kind in select distinct value->>'kind' from jsonb_array_elements(p_records) loop
    insert into public.halo_kind_revisions(kind,revision) values(changed_kind,1)
    on conflict(kind) do update set revision=public.halo_kind_revisions.revision+1;
  end loop;
  for r in select value from jsonb_array_elements(p_events) loop
    insert into public.halo_events(id,asset_id,kind,content,created_at)
      values((r->>'id')::uuid,r->>'asset_id',r->>'kind',r->'content',(r->>'created_at')::timestamptz);
  end loop;
  return jsonb_build_object('committed',true);
end $$;
create or replace function public.halo_health()
returns jsonb language sql security definer set search_path = '' as $$
  select jsonb_build_object('schema_version',2,'database','connected','storage',
    case when exists(select 1 from storage.buckets where id='halo-evidence' and not public) then 'private' else 'misconfigured' end);
$$;
notify pgrst,'reload schema';
commit;
