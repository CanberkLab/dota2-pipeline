-- Daily trend per hero: useful to spot the effect of balance patches.
select
    started_date,
    hero_id,
    count(*) as games,
    sum(cast(won as integer)) as wins,
    sum(cast(won as integer)) * 1.0 / count(*) as win_rate
from {{ ref('fct_match_heroes') }}
group by 1, 2
