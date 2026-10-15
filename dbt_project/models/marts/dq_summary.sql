-- Data quality report: rejected matches by rule and by day they were ingested.
with per_day as (
    select cast(ingested_at as date) as ingest_date, count(*) as total_rows
    from {{ ref('stg_public_matches') }}
    group by 1
),

failures as (
    select cast(ingested_at as date) as ingest_date, dq_failure_reason, count(*) as failed_rows
    from {{ ref('stg_public_matches') }}
    where not is_valid
    group by 1, 2
)

select
    f.ingest_date,
    f.dq_failure_reason,
    f.failed_rows,
    p.total_rows,
    round(100.0 * f.failed_rows / p.total_rows, 3) as pct_of_day
from failures f
join per_day p using (ingest_date)
order by f.ingest_date, f.failed_rows desc
