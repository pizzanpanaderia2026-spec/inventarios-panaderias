-- Store only the private Cloudflare R2 object key for each bakery photo.
alter table public.panaderias add column if not exists foto_key text;
comment on column public.panaderias.foto_key is 'Clave del objeto de fotografía privada del local en Cloudflare R2';
