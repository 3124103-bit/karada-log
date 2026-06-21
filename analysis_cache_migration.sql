create table public.analysis_cache (
  kind text not null,
  analysis_date date not null,
  input_hash text not null,
  content text not null,
  created_at timestamptz not null default now(),
  primary key (kind, analysis_date)
);

alter table public.analysis_cache enable row level security;
grant all privileges on table public.analysis_cache to service_role;
