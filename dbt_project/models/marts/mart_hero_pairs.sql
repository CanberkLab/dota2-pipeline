-- Same-team hero pairs. hero_a < hero_b so each pair appears once.
-- Each team yields C(5,2)=10 pairs, so a match contributes 20 rows to the join.
with team_rows as (
    select match_id, side, hero_id, won
    from {{ ref('fct_match_heroes') }}
)

select
    a.hero_id as hero_a,
    b.hero_id as hero_b,
    da.hero_name as hero_a_name,
    db.hero_name as hero_b_name,
    count(*) as games,
    sum(cast(a.won as integer)) as wins,
    sum(cast(a.won as integer)) * 1.0 / count(*) as win_rate
from team_rows a
join team_rows b
  on a.match_id = b.match_id and a.side = b.side and a.hero_id < b.hero_id
left join {{ ref('dim_heroes') }} da on da.hero_id = a.hero_id
left join {{ ref('dim_heroes') }} db on db.hero_id = b.hero_id
group by 1, 2, 3, 4
having count(*) >= {{ var('min_pair_games') }}
