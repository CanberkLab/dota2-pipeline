select
    started_date,
    count(*)                                         as matches,
    avg(duration_min)                                as avg_duration_min,
    avg(cast(radiant_win as integer))                as radiant_win_rate
from {{ ref('fct_matches') }}
group by 1
order by 1
