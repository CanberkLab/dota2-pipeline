-- Hero performance per rank medal (the meta differs a lot between Herald and Immortal).
with rank_totals as (
    select rank_medal_id, count(distinct match_id) as matches
    from {{ ref('fct_match_heroes') }}
    where rank_medal_id is not null
    group by 1
),

hero as (
    select
        rank_medal_id, hero_id,
        count(*) as games,
        sum(cast(won as integer)) as wins
    from {{ ref('fct_match_heroes') }}
    where rank_medal_id is not null
    group by 1, 2
)

select
    h.rank_medal_id,
    r.rank_medal_name,
    h.hero_id,
    d.hero_name,
    h.games,
    h.wins,
    h.wins * 1.0 / h.games      as win_rate,
    h.games * 1.0 / t.matches   as pick_rate
from hero h
join rank_totals t using (rank_medal_id)
join {{ ref('rank_tiers') }} r using (rank_medal_id)
left join {{ ref('dim_heroes') }} d using (hero_id)
