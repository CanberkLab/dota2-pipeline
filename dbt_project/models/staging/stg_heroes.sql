{{ config(materialized='view') }}

-- Latest hero snapshot only (the raw table keeps the history).
select
    id               as hero_id,
    name             as hero_code,
    localized_name   as hero_name,
    primary_attr,
    attack_type,
    roles,
    snapshot_date
from {{ source('raw', 'heroes_snapshots') }}
qualify snapshot_date = max(snapshot_date) over ()
