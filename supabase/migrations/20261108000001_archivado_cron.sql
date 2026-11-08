-- Supabase Cron ejecuta el disparador diario a las 08:00 UTC (02:00 en Puebla).
-- El secreto se obtiene desde Vault; nunca se guarda en el repositorio.
create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.schedule(
  'archivado-inventarios-diario',
  '0 8 * * *',
  $job$
    select net.http_post(
      url := 'https://inventarios-panaderias.onrender.com/api/internal/archivado/ejecutar',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'X-Archivado-Secret',
        (select decrypted_secret from vault.decrypted_secrets where name = 'archivado_cron_secret')
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 30000
    );
  $job$
);
