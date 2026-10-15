select
    hero_id,
    hero_name,
    hero_code,
    primary_attr,
    attack_type,
    roles
from {{ ref('stg_heroes') }}
