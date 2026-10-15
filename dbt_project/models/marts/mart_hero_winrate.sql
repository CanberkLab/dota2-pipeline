-- Overall hero performance. win_rate_low/high is the Wilson 95% interval: a hero
-- with 60% over 20 games is NOT better than one with 53% over 5,000 games, and
-- the interval makes that visible.
with total as (
    select count(*) as total_matches from {{ ref('fct_matches') }}
),

hero as (
    select hero_id, count(*) as games, sum(cast(won as integer)) as wins
    from {{ ref('fct_match_heroes') }}
    group by 1
),

stats as (
    select
        hero_id, games, wins,
        wins * 1.0 / games as p,
        1.96 as z
    from hero
)

select
    s.hero_id,
    d.hero_name,
    d.primary_attr,
    d.attack_type,
    s.games,
    s.wins,
    s.p                                   as win_rate,
    s.games * 1.0 / t.total_matches       as pick_rate,
    (s.p + s.z*s.z/(2*s.games)
        - s.z * sqrt((s.p*(1-s.p) + s.z*s.z/(4*s.games)) / s.games))
        / (1 + s.z*s.z/s.games)           as win_rate_low,
    (s.p + s.z*s.z/(2*s.games)
        + s.z * sqrt((s.p*(1-s.p) + s.z*s.z/(4*s.games)) / s.games))
        / (1 + s.z*s.z/s.games)           as win_rate_high
from stats s
cross join total t
left join {{ ref('dim_heroes') }} d using (hero_id)
