-- La función se ejecuta mediante el event trigger ensure_rls.
-- No debe ser invocable directamente por roles de aplicación.
-- Esto no elimina ni deshabilita el event trigger existente.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
