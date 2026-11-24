
alter table public.auditoria_ventas enable row level security;
revoke all privileges on table public.auditoria_ventas from public, anon, authenticated;
grant all privileges on table public.auditoria_ventas to service_role;
revoke all on function public.cerrar_dias_automaticamente() from public, anon, authenticated;
grant execute on function public.cerrar_dias_automaticamente() to service_role;
