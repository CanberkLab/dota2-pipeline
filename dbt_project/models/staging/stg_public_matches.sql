{{ config(materialized='view') }}

{#
  Staging: type, derive and FLAG. Nothing is dropped here so dq_summary can show
  exactly what was rejected and why.
  rank_tier encoding: tens digit = medal (1 Herald ... 8 Immortal), ones digit = stars.
#}

with source as (

    select * from {{ source('raw', 'public_matches') }}

),

typed as (

    select
        match_id,
        match_seq_num,
        make_timestamp(start_time * 1000000)  as started_at,   -- UTC
        duration                              as duration_seconds,
        duration / 60.0                       as duration_min,
        radiant_win,
        avg_rank_tier,
        num_rank_tier,
        case when avg_rank_tier >= 10 and avg_rank_tier < 90
             then cast(floor(avg_rank_tier / 10) as integer) end as rank_medal_id,
        game_mode,
        lobby_type,
        cluster,
        radiant_team,
        dire_team,
        ingested_at,
        _source_file,
        _loaded_at
    from source

),

flagged as (

    select
        *,
        case
            when started_at is null or started_at < timestamp '2013-01-01'
                then 'invalid_start_time'
            when radiant_win is null
                then 'missing_result'
            when radiant_team is null or dire_team is null
                 or len(radiant_team) <> 5 or len(dire_team) <> 5
                then 'invalid_team_size'
            when len(list_distinct(list_concat(radiant_team, dire_team))) <> 10
                then 'duplicate_hero_in_match'
            when duration_seconds is null or duration_seconds < 300 or duration_seconds > 10800
                then 'invalid_duration'
        end as dq_failure_reason
    from typed

)

select
    *,
    dq_failure_reason is null as is_valid
from flagged
