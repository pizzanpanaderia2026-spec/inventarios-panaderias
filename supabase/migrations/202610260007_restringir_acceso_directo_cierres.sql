-- Estas tablas se administran únicamente desde el backend con service_role.
-- Sin políticas RLS no basta con confiar en el bloqueo por filas: quitamos también los permisos SQL directos.
revoke all privileges on table public.cierres_diarios from anon, authenticated;
revoke all privileges on table public.auditoria_inventario from anon, authenticated;
grant select, insert, update, delete on table public.cierres_diarios to service_role;
grant select, insert, update, delete on table public.auditoria_inventario to service_role;
