"""
Admin analytics over any time frame.

Every report is one plain SQL query, kept here as text so the admin page can
show exactly what ran ("How is this computed?"). Queries take named parameters:

    :start, :end            the chosen time frame (dates, inclusive)
    :prev_start, :prev_end  the same-length period just before it (for % change)
    :bucket                 'day', 'week' or 'month' for the timeline
    :year                   goal year (the year of :end)

A diary entry counts on the day the book was read (date_read), or the day it
was logged if no date was given. The admin session bypasses row-level security
on diary_entry (app.role = 'admin'), so private diaries are included in totals.
"""
from datetime import date, timedelta

from app.database import db

READ_ON = "COALESCE(d.date_read, d.created_at::date)"

REPORTS = [
    {
        "key": "kpis",
        "title": "Headline numbers",
        "about": "Totals for the period, each compared with the same-length period before it. "
                 "One pass over the diary, split into the two periods with aggregate FILTER clauses.",
        "sql": f"""
SELECT count(*)                       FILTER (WHERE cur)     AS books_logged,
       count(*)                       FILTER (WHERE NOT cur) AS books_logged_prev,
       count(DISTINCT user_id)        FILTER (WHERE cur)     AS active_readers,
       count(DISTINCT user_id)        FILTER (WHERE NOT cur) AS active_readers_prev,
       count(DISTINCT book_id)        FILTER (WHERE cur)     AS unique_books,
       count(DISTINCT book_id)        FILTER (WHERE NOT cur) AS unique_books_prev,
       COALESCE(sum(page_count)       FILTER (WHERE cur), 0)     AS pages_read,
       COALESCE(sum(page_count)       FILTER (WHERE NOT cur), 0) AS pages_read_prev,
       round(avg(rating)              FILTER (WHERE cur), 2)     AS avg_rating,
       round(avg(rating)              FILTER (WHERE NOT cur), 2) AS avg_rating_prev,
       count(review_text)             FILTER (WHERE cur)     AS reviews,
       count(review_text)             FILTER (WHERE NOT cur) AS reviews_prev,
       (SELECT count(*) FROM users WHERE created_at::date BETWEEN :start AND :end)           AS new_readers,
       (SELECT count(*) FROM users WHERE created_at::date BETWEEN :prev_start AND :prev_end) AS new_readers_prev
FROM (
    SELECT d.user_id, d.book_id, d.rating, d.review_text, b.page_count,
           {READ_ON} >= :start AS cur
    FROM diary_entry d
    JOIN book b USING (book_id)
    WHERE {READ_ON} BETWEEN :prev_start AND :end
) AS periods""",
        "one": True,
    },
    {
        "key": "timeline",
        "title": "Reading activity over time",
        "about": "generate_series builds every day / week / month in the period, so empty ones show as 0; "
                 "diary entries and sign-ups are counted into each with date_trunc.",
        "sql": f"""
WITH buckets AS (
    SELECT generate_series(date_trunc(:bucket, :start::timestamp),
                           date_trunc(:bucket, :end::timestamp),
                           ('1 ' || :bucket)::interval) AS period
)
SELECT bk.period::date                AS period,
       count(d.entry_id)              AS books_logged,
       count(DISTINCT d.user_id)      AS readers,
       count(d.review_text)           AS reviews,
       (SELECT count(*) FROM users u
         WHERE date_trunc(:bucket, u.created_at::timestamp) = bk.period) AS new_readers
FROM buckets bk
LEFT JOIN diary_entry d
       ON date_trunc(:bucket, {READ_ON}::timestamp) = bk.period
      AND {READ_ON} BETWEEN :start AND :end
GROUP BY bk.period
ORDER BY bk.period""",
    },
    {
        "key": "most_read",
        "title": "Most read books",
        "about": "Books ranked by distinct readers, then total logs (re-reads count). "
                 "DENSE_RANK is a window function, so tied books share a rank.",
        "sql": f"""
SELECT DENSE_RANK() OVER (ORDER BY count(DISTINCT d.user_id) DESC, count(*) DESC) AS rank,
       bs.title,
       bs.authors[1]                            AS author,
       count(DISTINCT d.user_id)                AS readers,
       count(*)                                 AS logs,
       round(avg(d.rating), 2)                  AS avg_rating,
       count(*) FILTER (WHERE d.is_liked)       AS likes
FROM diary_entry d
JOIN book_summary bs USING (book_id)
WHERE {READ_ON} BETWEEN :start AND :end
GROUP BY bs.book_id, bs.title, bs.authors
ORDER BY rank, bs.title
LIMIT 15""",
    },
    {
        "key": "top_rated",
        "title": "Highest rated books (2+ ratings)",
        "about": "Average reader rating in the period. HAVING drops books with a single rating, "
                 "so one 5-star review can't top the chart.",
        "sql": f"""
SELECT bs.title,
       bs.authors[1]              AS author,
       count(d.rating)            AS ratings,
       round(avg(d.rating), 2)    AS avg_rating,
       min(d.rating)              AS lowest,
       max(d.rating)              AS highest
FROM diary_entry d
JOIN book_summary bs USING (book_id)
WHERE {READ_ON} BETWEEN :start AND :end
  AND d.rating IS NOT NULL
GROUP BY bs.book_id, bs.title, bs.authors
HAVING count(d.rating) >= 2
ORDER BY avg_rating DESC, ratings DESC
LIMIT 10""",
    },
    {
        "key": "genres",
        "title": "Genres read",
        "about": "Logs per genre (a book can have several). share_pct divides each genre by the total "
                 "with a window function: sum(count(*)) OVER ().",
        "sql": f"""
SELECT g.name                                              AS genre,
       count(*)                                            AS logs,
       count(DISTINCT d.user_id)                           AS readers,
       round(avg(d.rating), 2)                             AS avg_rating,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)  AS share_pct
FROM diary_entry d
JOIN book_genre bg USING (book_id)
JOIN genre g       USING (genre_id)
WHERE {READ_ON} BETWEEN :start AND :end
GROUP BY g.name
ORDER BY logs DESC
LIMIT 12""",
    },
    {
        "key": "genre_momentum",
        "title": "Rising and falling genres",
        "about": "Each genre's logs in this period versus the previous one: a CTE counts both periods in "
                 "one scan with FILTER, then NULLIF avoids dividing by zero for genres that are new.",
        "sql": f"""
WITH counts AS (
    SELECT g.name AS genre,
           count(*) FILTER (WHERE {READ_ON} >= :start) AS this_period,
           count(*) FILTER (WHERE {READ_ON} <  :start) AS previous_period
    FROM diary_entry d
    JOIN book_genre bg USING (book_id)
    JOIN genre g       USING (genre_id)
    WHERE {READ_ON} BETWEEN :prev_start AND :end
    GROUP BY g.name
)
SELECT genre, this_period, previous_period,
       round(100.0 * (this_period - previous_period) / NULLIF(previous_period, 0)) AS change_pct
FROM counts
ORDER BY this_period - previous_period DESC, this_period DESC
LIMIT 10""",
    },
    {
        "key": "authors",
        "title": "Most read authors",
        "about": "Joins the diary to authors through the book_author bridge table (many-to-many).",
        "sql": f"""
SELECT a.name                       AS author,
       count(*)                     AS logs,
       count(DISTINCT d.book_id)    AS books,
       count(DISTINCT d.user_id)    AS readers,
       round(avg(d.rating), 2)      AS avg_rating
FROM diary_entry d
JOIN book_author ba USING (book_id)
JOIN author a       USING (author_id)
WHERE {READ_ON} BETWEEN :start AND :end
GROUP BY a.author_id, a.name
ORDER BY logs DESC, readers DESC
LIMIT 10""",
    },
    {
        "key": "ratings",
        "title": "Rating distribution",
        "about": "generate_series(0.5, 5.0, 0.5) lists every possible half-star rating; the LEFT JOIN "
                 "keeps ratings nobody gave, at 0.",
        "sql": f"""
SELECT s.rating,
       count(d.entry_id) AS entries
FROM generate_series(0.5, 5.0, 0.5) AS s(rating)
LEFT JOIN diary_entry d
       ON d.rating = s.rating
      AND {READ_ON} BETWEEN :start AND :end
GROUP BY s.rating
ORDER BY s.rating""",
    },
    {
        "key": "weekday",
        "title": "Which day people finish books",
        "about": "EXTRACT(ISODOW ...) gives 1 = Monday ... 7 = Sunday.",
        "sql": f"""
SELECT s.dow,
       (ARRAY['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])[s.dow] AS day,
       count(d.entry_id) AS books_logged
FROM generate_series(1, 7) AS s(dow)
LEFT JOIN diary_entry d
       ON EXTRACT(ISODOW FROM {READ_ON}) = s.dow
      AND {READ_ON} BETWEEN :start AND :end
GROUP BY s.dow
ORDER BY s.dow""",
    },
    {
        "key": "readers",
        "title": "Most active readers",
        "about": "Per-reader totals ranked with RANK(). Re-reads = logs minus distinct books.",
        "sql": f"""
SELECT RANK() OVER (ORDER BY count(*) DESC)      AS rank,
       u.username,
       count(*)                                  AS books_logged,
       count(*) - count(DISTINCT d.book_id)      AS rereads,
       COALESCE(sum(b.page_count), 0)            AS pages,
       count(d.review_text)                      AS reviews,
       round(avg(d.rating), 2)                   AS avg_rating
FROM diary_entry d
JOIN users u USING (user_id)
JOIN book b  USING (book_id)
WHERE {READ_ON} BETWEEN :start AND :end
GROUP BY u.user_id, u.username
ORDER BY rank, u.username
LIMIT 10""",
    },
    {
        "key": "eras",
        "title": "When the books were written",
        "about": "Groups books by the decade they were published, with a CASE for anything before 1900.",
        "sql": f"""
SELECT CASE WHEN b.pub_year < 1900 THEN 'Before 1900'
            ELSE (b.pub_year / 10 * 10)::text || 's' END AS era,
       count(*)                AS books_logged,
       round(avg(d.rating), 2) AS avg_rating
FROM diary_entry d
JOIN book b USING (book_id)
WHERE {READ_ON} BETWEEN :start AND :end
  AND b.pub_year IS NOT NULL
GROUP BY era
ORDER BY min(b.pub_year)""",
    },
    {
        "key": "lengths",
        "title": "Book length",
        "about": "CASE buckets the page count; ordering by min(page_count) keeps the buckets in size order.",
        "sql": f"""
SELECT CASE WHEN b.page_count < 200 THEN 'Short (under 200)'
            WHEN b.page_count < 400 THEN 'Medium (200-399)'
            WHEN b.page_count < 600 THEN 'Long (400-599)'
            ELSE 'Epic (600+)' END     AS length,
       count(*)                       AS books_logged,
       round(avg(d.rating), 2)        AS avg_rating
FROM diary_entry d
JOIN book b USING (book_id)
WHERE {READ_ON} BETWEEN :start AND :end
  AND b.page_count IS NOT NULL
GROUP BY length
ORDER BY min(b.page_count)""",
    },
    {
        "key": "shelves",
        "title": "Most wanted books (shelves right now)",
        "about": "Current Want to Read / Reading Now shelves, not limited to the time frame.",
        "sql": """
SELECT b.title,
       count(*) FILTER (WHERE s.status = 'want_to_read')      AS want_to_read,
       count(*) FILTER (WHERE s.status = 'currently_reading') AS reading_now
FROM shelf s
JOIN book b USING (book_id)
GROUP BY b.book_id, b.title
ORDER BY count(*) DESC, b.title
LIMIT 10""",
    },
    {
        "key": "funnel",
        "title": "Engagement funnel (all readers)",
        "about": "How far readers go: sign up, log a book, review, make a list, follow someone. "
                 "Each step is a scalar subquery; UNION ALL turns them into rows.",
        "sql": """
SELECT 1 AS step, 'Signed up'        AS stage, (SELECT count(*) FROM users)                          AS readers
UNION ALL SELECT 2, 'Logged a book',   (SELECT count(DISTINCT user_id) FROM diary_entry)
UNION ALL SELECT 3, 'Wrote a review',  (SELECT count(DISTINCT user_id) FROM diary_entry WHERE review_text IS NOT NULL)
UNION ALL SELECT 4, 'Made a list',     (SELECT count(DISTINCT user_id) FROM list)
UNION ALL SELECT 5, 'Follows someone', (SELECT count(DISTINCT follower_id) FROM user_follow)
ORDER BY step""",
    },
    {
        "key": "goals",
        "title": "Reading goals",
        "about": "Progress towards each reader's goal for the year. books_finished is kept up to date "
                 "by a trigger on diary_entry.",
        "sql": """
SELECT u.username,
       g.target_books,
       g.books_finished,
       round(100.0 * g.books_finished / g.target_books) AS pct,
       CASE WHEN g.books_finished >= g.target_books THEN 'Completed'
            WHEN g.books_finished >= g.target_books
                 * EXTRACT(DOY FROM LEAST(:end::date, make_date(:year, 12, 31))) / 365.0
                 THEN 'On track'
            ELSE 'Behind' END                            AS status
FROM reading_goal g
JOIN users u USING (user_id)
WHERE g.year = :year
ORDER BY pct DESC, u.username""",
    },
    {
        "key": "social",
        "title": "Most followed readers",
        "about": "LEFT JOIN keeps readers with no followers; following is a correlated subquery.",
        "sql": """
SELECT u.username,
       count(f.follower_id) AS followers,
       (SELECT count(*) FROM user_follow f2 WHERE f2.follower_id = u.user_id) AS following,
       (SELECT count(*) FROM list l WHERE l.user_id = u.user_id)              AS lists
FROM users u
LEFT JOIN user_follow f ON f.followee_id = u.user_id
GROUP BY u.user_id, u.username
ORDER BY followers DESC, u.username
LIMIT 10""",
    },
]

RANGES = {"7d": 7, "30d": 30, "90d": 90, "12m": 365}


def _to_psycopg(sql: str) -> str:
    """:name -> %(name)s, leaving ::casts alone."""
    import re
    return re.sub(r"(?<!:):([a-z_]+)", r"%(\1)s", sql)


def resolve_range(range_key: str, start=None, end=None):
    today = date.today()
    if range_key == "custom" and start and end:
        start, end = min(start, end), max(start, end)
    elif range_key == "ytd":
        start, end = date(today.year, 1, 1), today
    elif range_key == "last_year":
        start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    elif range_key == "all":
        with db.cursor() as cur:
            cur.execute(f"SELECT min({READ_ON}) AS first FROM diary_entry d")
            first = cur.fetchone()["first"]
        start, end = (first or today - timedelta(days=365)), today
    else:
        range_key = range_key if range_key in RANGES else "30d"
        start, end = today - timedelta(days=RANGES[range_key] - 1), today
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    bucket = "day" if days <= 31 else "week" if days <= 180 else "month"
    return {"start": start, "end": end, "prev_start": prev_start, "prev_end": prev_end,
            "bucket": bucket, "year": end.year, "days": days, "range": range_key}


def insights(range_key="30d", start=None, end=None):
    params = resolve_range(range_key, start, end)
    sections = {}
    with db.cursor() as cur:
        for r in REPORTS:
            cur.execute(_to_psycopg(r["sql"]), params)
            rows = cur.fetchall()
            sections[r["key"]] = {"title": r["title"], "about": r["about"], "sql": r["sql"].strip(),
                                  "rows": rows[0] if r.get("one") else rows}
    meta = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in params.items()}
    return {"range": meta, "sections": sections}
