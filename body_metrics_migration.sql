create table public.body_metrics (
  id uuid primary key default gen_random_uuid(),
  logged_date date not null unique,
  weight numeric,
  bmi numeric,
  body_fat_percentage numeric,
  body_fat_mass numeric,
  visceral_fat_index numeric,
  skeletal_muscle_mass numeric,
  estimated_bone_mass numeric,
  body_water_mass numeric,
  basal_metabolic_rate numeric,
  appendicular_lean_mass numeric,
  smi numeric,
  memo text,
  created_at timestamptz not null default now()
);

alter table public.body_metrics enable row level security;
grant all privileges on table public.body_metrics to service_role;

insert into public.body_metrics (
  logged_date, weight, bmi, body_fat_percentage, body_fat_mass,
  visceral_fat_index, skeletal_muscle_mass, estimated_bone_mass,
  body_water_mass, basal_metabolic_rate, appendicular_lean_mass, smi
) values (
  '2026-03-20', 75.75, 25.9, 15.8, 11.95,
  60, 32.65, 3.05, 46.70, 1770, 27.10, 9.3
) on conflict (logged_date) do update set
  weight = excluded.weight,
  bmi = excluded.bmi,
  body_fat_percentage = excluded.body_fat_percentage,
  body_fat_mass = excluded.body_fat_mass,
  visceral_fat_index = excluded.visceral_fat_index,
  skeletal_muscle_mass = excluded.skeletal_muscle_mass,
  estimated_bone_mass = excluded.estimated_bone_mass,
  body_water_mass = excluded.body_water_mass,
  basal_metabolic_rate = excluded.basal_metabolic_rate,
  appendicular_lean_mass = excluded.appendicular_lean_mass,
  smi = excluded.smi;
