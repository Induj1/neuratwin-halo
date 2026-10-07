-- A minimal directory for the administrator's team-access screen.
-- Auth credentials and metadata are never returned. Client roles cannot call it.
begin;
create or replace function public.halo_team_directory()
returns table(user_id uuid,email text,role text,active boolean,created_at timestamptz)
language sql security definer set search_path = '' as $$
  select m.user_id,u.email::text,m.role,m.active,m.created_at
  from public.halo_members m join auth.users u on u.id=m.user_id
  order by m.created_at,m.user_id;
$$;
create or replace function public.halo_account_by_email(p_email text)
returns table(user_id uuid)
language sql security definer set search_path = '' as $$
  select id from auth.users where lower(email)=lower(trim(p_email)) limit 1;
$$;
revoke all on function public.halo_team_directory() from public,anon,authenticated;
revoke all on function public.halo_account_by_email(text) from public,anon,authenticated;
grant execute on function public.halo_team_directory() to service_role;
grant execute on function public.halo_account_by_email(text) to service_role;
notify pgrst,'reload schema';
commit;
