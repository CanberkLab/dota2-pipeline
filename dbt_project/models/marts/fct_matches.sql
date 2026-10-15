{{
    config(
        materialized='incremental',
        unique_key='match_id',
        incremental_strategy='delete+insert'
    )
}}

-- One row per VALID match. Incremental on _loaded_at: a run only processes
-- files loaded since the previous run.

select
    match_id,
    started_at,
    cast(started_at as date) as started_date,
    duration_min,
    radiant_win,
    avg_rank_tier,
    rank_medal_id,
    game_mode,
    lobby_type,
    cluster,
    radiant_team,
    dire_team,
    _source_file,
    _loaded_at
from {{ ref('stg_public_matches') }}
where is_valid

{% if is_incremental() %}
  and _loaded_at > (select coalesce(max(_loaded_at), timestamp '1900-01-01') from {{ this }})
{% endif %}
