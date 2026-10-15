select match_id
from {{ ref('fct_match_heroes') }}
group by 1
having sum(cast(won as integer)) <> 5
