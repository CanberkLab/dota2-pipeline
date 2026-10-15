{{
    config(
        materialized='incremental',
        unique_key='match_hero_key',
        incremental_strategy='delete+insert'
    )
}}

-- Grain: one row per match x hero (10 rows per match). The two team arrays are
-- unnested into rows so hero statistics become simple GROUP BYs.

with picks as (

    select
        m.match_id, m.started_at, m.started_date, m.duration_min,
        m.avg_rank_tier, m.rank_medal_id, m._loaded_at,
        'radiant'        as side,
        m.radiant_win    as won,
        u.hero_id
    from {{ ref('fct_matches') }} m, unnest(m.radiant_team) as u(hero_id)

    union all

    select
        m.match_id, m.started_at, m.started_date, m.duration_min,
        m.avg_rank_tier, m.rank_medal_id, m._loaded_at,
        'dire'           as side,
        not m.radiant_win as won,
        u.hero_id
    from {{ ref('fct_matches') }} m, unnest(m.dire_team) as u(hero_id)

)

select
    match_id || '-' || side || '-' || hero_id as match_hero_key,
    *
from picks

{% if is_incremental() %}
where _loaded_at > (select coalesce(max(_loaded_at), timestamp '1900-01-01') from {{ this }})
{% endif %}
