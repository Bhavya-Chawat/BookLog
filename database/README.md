# BookLog catalogue snapshot

**`booklog-database.zip`** (about 13 MB) holds the PostgreSQL database that `setup.bat`
restores on a fresh install:

| File inside the zip | What it is | Use it for |
|---|---|---|
| `booklog.dump` | PostgreSQL custom-format backup (compressed) | Restoring the database |
| `booklog.sql` | The same backup as plain SQL | Reading the schema, triggers, policies and data |

## What is in it

The full schema (every table, constraint, index, trigger, row-level security policy, view and
materialized view, plus the mood-tag rules and their trigger), with data in the **catalogue tables
only**:

| Table | Rows |
|---|---|
| `book` | 24,884 |
| `author` / `book_author` | 16,156 authors |
| `publisher` | 7,770 |
| `genre` / `book_genre` | 76 genres |
| `tag` / `book_tag` / `mood_rule` | 13 moods, 42,744 mood tags |

There are **no users and no activity**: `users`, `diary_entry`, `shelf`, `reading_goal`,
`list`, `list_book`, follows, likes, comments, reports, `audit_log` and `sync_outbox` are empty.
Setup starts every id counter at 1, so the first person to sign in is user 1.

## Restore

**Windows:** run `setup.bat` from the repo root (see [docs/SETUP.md](../docs/SETUP.md)). It unzips
the snapshot and restores it **only when there is no `booklog` database yet**, so an existing
database and its users are never touched.

**macOS / Linux:** from the repo root, with PostgreSQL running:

```bash
unzip -o database/booklog-database.zip -d database/ && sh backend/scripts/restore.sh database/booklog.dump
```

`restore.sh` creates the `booklog` database (and stops if it already exists), restores it,
re-creates the `booklog_app` / `booklog_reports` roles (a dump can't carry roles), and rebuilds
the Neo4j graph if Neo4j is running.

## Making a new snapshot

To refresh the zip from your own database **without** your users and activity, dump the schema
and only the catalogue data. Run from the repo root in Git Bash, as any role that can read
every table (for example `booklog_app` with the `DATABASE_URL` from `backend/.env`):

```bash
PG="/c/Program Files/PostgreSQL/18/bin"
URL=$(grep '^DATABASE_URL=' backend/.env | cut -d= -f2- | tr -d '\r')
EX=""; for t in users user_genre diary_entry shelf reading_goal list list_book list_like review_like \
  comment review_report user_follow author_follow audit_log sync_outbox \
  mv_most_read_books mv_active_users mv_genre_trends; do EX="$EX --exclude-table-data=public.$t"; done
"$PG/pg_dump.exe" -d "$URL" -Fc --no-owner --no-privileges $EX -f database/booklog.dump
"$PG/pg_restore.exe" -f database/booklog.sql database/booklog.dump
```

Then zip `booklog.dump` and `booklog.sql` into `booklog-database.zip`. Always write with `-f`:
piping `pg_dump` through PowerShell corrupts non-English text. The unzipped files are in
`.gitignore`; only the zip is committed.
