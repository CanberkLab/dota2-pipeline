-- Singular test: returns offending rows; passes when none are returned.
select match_id
from {{ ref('fct_match_heroes') }}
group by 1
having count(*) <> 10
