-- Endurecimiento de permisos de la función usada por el event trigger ensure_rls.
-- El disparador existente sigue siendo el mecanismo que activa RLS al crear tablas;
-- los roles de aplicación no necesitan ejecutar esta función directamente.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

-- Las tablas de cierres y auditoría se consumen desde el backend con service_role.
-- RLS permanece habilitado y no se crean políticas para acceso directo del cliente.
-- No otorgar acceso a anon/authenticated sin diseñar y probar políticas específicas.
