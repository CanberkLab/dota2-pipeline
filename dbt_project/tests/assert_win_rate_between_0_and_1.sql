select hero_id
from {{ ref('mart_hero_winrate') }}
where win_rate < 0 or win_rate > 1
   or win_rate_low > win_rate or win_rate_high < win_rate
