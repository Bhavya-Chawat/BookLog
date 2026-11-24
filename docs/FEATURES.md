# BookLog: features and databases

This document explains every feature of BookLog, which database each one uses, and what each of the three databases stores and why. For installing and running the project, see the [README](../README.md).

**Contents**

1. [The big picture](#1-the-big-picture)
2. [Features](#2-features)
3. [PostgreSQL: the main database](#3-postgresql-the-main-database)
4. [Neo4j: the social graph](#4-neo4j-the-social-graph)
5. [MongoDB: documents and logs](#5-mongodb-documents-and-logs)
6. [Firebase: sign-in only](#6-firebase-sign-in-only)
7. [Keeping the databases consistent](#7-keeping-the-databases-consistent)
8. [Admin analytics and the SQL behind them](#8-admin-analytics-and-the-sql-behind-them)
9. [Demo data](#9-demo-data)
10. [API reference](#10-api-reference)

---

## 1. The big picture

```
 Browser (React, http://localhost:5173)
    │  Google sign-in through Firebase gives an ID token
    ▼
 FastAPI (http://localhost:8000)  ── verifies the token with Firebase Admin
    │
    ├── PostgreSQL ── source of truth: catalogue, users, diary, lists, social, moderation
    │       │
    │       └── sync_outbox table ──► background worker ──► Neo4j  (follows, ratings)
    │                                                  └──► MongoDB (clean-up on account delete)
    ├── Neo4j ──────── graph questions: friends of friends, steps apart, taste match
    └── MongoDB ────── takes, messages, chatbot conversations, activity logs, caches
```

| Database | Role | Why this database |
|---|---|---|
| **PostgreSQL** | The source of truth. Everything that must be correct lives here: the book catalogue, accounts, diary entries, ratings, lists, follows, likes, comments, shelves, goals, reports, the audit log. | ACID transactions, foreign keys, CHECK constraints, triggers, row-level security, materialized views, fast fuzzy search with trigram indexes. |
| **Neo4j** | A copy of the social graph: who follows whom and who rated which book. | Questions about paths and neighbourhoods ("friends of friends", "how many steps apart", "readers with similar taste") are one short Cypher query instead of recursive SQL. |
| **MongoDB** | Data that is document-shaped, high-volume or temporary: book takes, direct messages, chatbot conversations, view/click/search logs, cached recommendations, online presence. | Flexible documents (a chat conversation is one document with a list of messages), cheap inserts for logs, TTL indexes that delete old cache entries automatically. |
| **Firebase Auth** | Google sign-in only. It stores no BookLog data. | Secure login without storing passwords ourselves. |

If Neo4j or MongoDB is down, the app keeps working. Social features fall back to SQL, logging is skipped and the features that need MongoDB (takes, messages, chatbot) say they are unavailable. `GET /health` shows the status of all three.

---

## 2. Features

Each feature lists what the user sees and which tables or collections it reads and writes.

### 2.1 Accounts and settings
- **Google sign-in** through Firebase. On the first sign-in, a row is created in `users` with the Firebase `uid`, a generated unique username and a `friend_code`.
- **Profile settings** (`/settings`): username (unique, format checked by a CHECK constraint), bio, language, **private diary** (`users.is_private`), favourite genres (`user_genre`, asked once after the first sign-in).
- **Export my data**: one JSON file with your profile, diary, shelves, lists, goals, follows and chatbot conversations (PostgreSQL plus MongoDB).
- **Delete my account**: one `DELETE FROM users` removes everything that belongs to you through `ON DELETE CASCADE`. Triggers queue the Neo4j and MongoDB clean-up in `sync_outbox`.
- **Roles**: `reader`, `moderator`, `admin` (`users.role`). Role changes are written to `audit_log`.

### 2.2 Catalogue, search and book pages
- **About 24,900 books** with covers, descriptions, page counts, years, publishers, authors (with bios and photos) and genres. Tables: `book`, `author`, `book_author`, `genre`, `book_genre`, `publisher`; the `book_summary` view joins them.
- **Search** (`/search`, and **Ctrl+K / ⌘K** from anywhere): live results as you type, by title, author, genre or ISBN, with typos allowed. It uses the `pg_trgm` similarity operators and the GIN trigram indexes `idx_book_title_trgm`, `idx_author_name_trgm`, `idx_genre_name_trgm`. Filters: genre, language, minimum rating. The page shows how many milliseconds PostgreSQL took.
- **Book page** (`/book/:title`): details, reading time, average rating and count (kept up to date by a trigger), reviews with likes and comments, **similar books** with the scoring explained (shared genres, authors and readers), which people you follow have read it, who is **reading it now**, and takes from Flips. Every view is logged to MongoDB `activity_logs`.
- **Author page** (`/author/:name`): bio, photo, all their books, **follow author** (`author_follow`).

### 2.3 Explore and Discover
- **Explore** (`/explore`): browse the whole catalogue with infinite scroll. Filter by **mood**, genre, decade, length and rating; sort by most read, highest rated, newest, oldest, shortest or longest. Grid or list view.
- **Moods**: every book carries mood tags (Dark, Cosy, Funny, Romantic, Tense, Mysterious, Adventurous, Emotional, Hopeful, Thought-provoking, Inspiring, Informative, Whimsical). They are shown on the book page and link to Explore filtered by that mood. Stored in the ER diagram's `tag` / `book_tag` tables, see [3.6](#36-mood-tags-tag--book_tag).
- **Home** (`/home`): book of the day, catalogue in numbers (books per decade), genre index, featured authors, trending books (most viewed and clicked in the last 7 days, an aggregation pipeline over MongoDB `activity_logs`), reading goal and personal recommendations.
- **Reader quiz** (`/quiz`): five questions build a named reader profile and pull real matching books from the catalogue.

### 2.4 Flips and takes
- **Flips** (`/flips`): flip through books one screen at a time. Tabs: For you, Latest, Following.
- **Takes**: a short note on a book (up to 280 characters) with an optional vibe: must read, cried, mind blown, slow start, comfort, overrated, fun fact, quote. Stored in MongoDB `book_takes` with an array of user IDs who liked it.
- **Privacy across two databases**: takes live in MongoDB, but who may see them is decided in PostgreSQL. A private account's takes are shown only to its followers (`users.is_private` + `user_follow`).

### 2.5 Diary, shelves, goals and lists
- **Log a book**: date read, half-star rating 0.5 to 5 (CHECK constraint), review, like. Edit and delete entries. A re-read is a new entry. Table `diary_entry`.
  - The **book rating trigger** (`trg_book_rating`) updates `book.avg_rating` and `book.ratings_count` incrementally on every insert, update or delete. It locks the book row, so two people rating at once cannot lose an update.
  - The **reading goal trigger** (`trg_goal_from_diary`) updates `reading_goal.books_finished`.
  - The **outbox trigger** (`trg_outbox_diary`) queues the rating for Neo4j.
- **Shelves**: Want to Read and Reading Now (`shelf`, one row per user and book).
- **My books** (`/library`): your diary by year, shelves and lists.
- **Reading goal**: a yearly target with a progress ring (`reading_goal`). When a goal is created, `trg_goal_init` counts the books you already finished that year.
- **Lists** (`/lists`): public or private ranked lists that you can drag to re-order. `list` + `list_book` with a unique position per list; the constraint is **deferred**, so the whole new order is saved in one transaction. Like (`list_like`) and comment (`comment` with `list_id`).
- **Reviews**: like (`review_like`), comment (`comment` with `entry_id`), report to moderators (`review_report`, one report per person per review).

### 2.6 Social
- **Follow and unfollow** readers (`user_follow`; a CHECK constraint forbids following yourself). Follower and following lists.
- **Feed** (`/feed`): what the people you follow logged, rated, reviewed and listed. One SQL query with `UNION ALL` over diary entries and lists, filtered by row-level security.
- **People** (`/people`): search readers (trigram index on `users.username`), **people you may know** (friends of friends in Neo4j, with a SQL fallback), **reading now** (what people you follow are reading).
- **Taste match and steps apart** on profiles: the percentage of books you both rated with close ratings, and the shortest follow path between you (Neo4j `shortestPath`).
- **Profiles** (`/u/:username`): diary, shelves, lists, goal, followers. A private diary is hidden from everyone except the owner and staff, enforced by row-level security in the database, not only by the API.
- **Messages** (`/messages`): direct messages between readers where at least one follows the other. Stored in MongoDB `messages`, grouped by a `thread` key, with read receipts.
- **Notifications**: new followers, likes and comments on your reviews and lists. Built with SQL; MongoDB `user_state` remembers when you last opened them. The app polls `/me/pulse` every ~20 seconds for the badge counts and to mark you online (`presence`).

### 2.7 Year in books (reading stats)
`/u/:username/stats`, by year or all time: books, pages, reviews, re-reads, books per month, rating spread, favourite genres and authors, your average against everyone else's, and highlights (top rated, longest, shortest, oldest, hidden gem). It reads the diary under row-level security, so private diaries stay private.

### 2.8 Recommendations
`/recommendations` mixes several sources, and each pick says why it was chosen:
- **Books liked by readers with similar taste**: Neo4j, users who rated the same books highly.
- **Books by authors you follow**: PostgreSQL `author_follow`.
- **What people you follow loved**: PostgreSQL `user_follow` + `diary_entry`.
- **Your favourite genres**: PostgreSQL `user_genre`.
- **Trending**: MongoDB `activity_logs`.

The result is cached in MongoDB `saved_recommendations` for one hour (TTL index) and cleared when you follow an author or change your genres.

### 2.9 Book assistant (chatbot)
`/chat`: ask for "a dark fantasy under 400 pages" or "something like Dune but shorter". The model (OpenAI) can only see books through a `search_books` tool that runs SQL against PostgreSQL, and only book IDs returned by that tool can be shown, so it cannot invent titles. Each conversation is one document in MongoDB `chat_sessions`. It needs `OPENAI_API_KEY`.

### 2.10 Admin and moderation (`/admin`)
| Tab | Who | What it does |
|---|---|---|
| **Reports** | admin | Most read books, most active readers and genre trends from the three materialized views (refreshed on open), plus sync status for Neo4j and MongoDB. |
| **Analytics** | admin | Detailed analytics for any time frame, each with its SQL. See [section 8](#8-admin-analytics-and-the-sql-behind-them). |
| **Moderation** | moderator, admin | Open, dismissed and removed review reports. Dismiss a report, or remove the review. |
| **Books / Authors / Genres** | admin | Add, edit and delete catalogue entries; genres can have a parent genre. Changes are recorded in `audit_log` by triggers. |
| **Users & roles** | admin | Search users, change roles. |
| **Audit log** | admin | Every audited change with old and new values as JSON. |

---

## 3. PostgreSQL: the main database

Database `booklog`. The API connects as `booklog_app`, which is deliberately **not a superuser**, because superusers bypass row-level security. Schema files: [schema.sql](../backend/db/schema.sql) (the ER diagram) plus [migrations](../backend/db/migrations/).

### 3.1 Tables

**Catalogue**
| Table | Stores | Notes |
|---|---|---|
| `book` | title, subtitle, ISBN, language, description, publication year, page count, cover URL, `avg_rating`, `ratings_count`, publisher | `avg_rating` and `ratings_count` are maintained by a trigger. Unique title and ISBN. |
| `author` | name, bio, photo URL | Unique name. |
| `book_author` | which author wrote which book | Many-to-many bridge. |
| `genre` | genre name, optional `parent_genre_id` | Self-referencing hierarchy. |
| `book_genre` | which genres a book belongs to | Many-to-many bridge. |
| `publisher` | name, country | One publisher has many books. |
| `tag`, `book_tag` | tags by type (`mood` or `theme`) and which books carry them | 13 mood tags on ~24,900 books (see 3.6). |
| `mood_rule` | for each mood: the genres and description keywords that give a book that mood, plus a one-line blurb | Added in migration 005. |

**Readers**
| Table | Stores | Notes |
|---|---|---|
| `users` | Firebase UID, username, email, role, bio, language, private flag, friend code, sign-up time | Named `users` because `user` is a reserved word. |
| `user_genre` | each reader's favourite genres | Many-to-many. |
| `diary_entry` | one logged read: user, book, rating, review, date read, liked, time logged | Row-level security. Rating between 0.5 and 5 in steps of 0.5. |
| `shelf` | Want to Read / Reading Now | Primary key (user, book). |
| `reading_goal` | yearly target and `books_finished` | `books_finished` is kept up to date by triggers. |

**Lists and social**
| Table | Stores |
|---|---|
| `list` | owner, name, description, public or private, created and updated times |
| `list_book` | books in a list with their rank (unique per list, deferrable) |
| `user_follow` | follower → followee, with time (no self-follow) |
| `author_follow` | reader follows an author |
| `review_like`, `list_like` | likes, one per person |
| `comment` | a comment on exactly one review **or** one list (CHECK constraint) |
| `review_report` | reported reviews: reason, status (open / dismissed / removed), who resolved it and when |

**System**
| Table | Stores |
|---|---|
| `audit_log` | table, operation, who made the change, old and new row as JSON, time |
| `sync_outbox` | changes waiting to be copied to Neo4j / MongoDB: target, operation, JSON payload, attempts, last error, time done |

### 3.2 Views
- `book_summary`: one row per book with its authors and genres aggregated into arrays. Used by most read queries.
- Materialized views for admin reports, owned by the read-only `booklog_reports` role: `mv_most_read_books`, `mv_active_users`, `mv_genre_trends` (logs and average rating per genre per month). Each has a unique index so it can be refreshed concurrently.

### 3.3 Triggers
| Trigger | On | What it does |
|---|---|---|
| `book_genre_moods`, `book_description_moods` → `trg_tag_moods` | `book_genre` insert, `book.description` update | Re-tags the book's moods. |
| `diary_entry_rating` → `trg_book_rating` | `diary_entry` insert / update / delete | Updates the book's average rating and rating count incrementally (no full recount). |
| `diary_entry_goal` → `trg_goal_from_diary` | `diary_entry` | Updates `reading_goal.books_finished` for the year read. |
| `reading_goal_init` → `trg_goal_init` | `reading_goal` insert | Counts books already finished that year. |
| `outbox_diary`, `outbox_follow`, `outbox_users` | diary, follows, users | Write a `sync_outbox` row **in the same transaction** as the change. |
| `audit_*` → `trg_audit` | book, author, genre, publisher, review reports, user role changes and deletions, diary deletions | Write old and new rows to `audit_log` with the acting user. |

### 3.4 Row-level security on `diary_entry`
Every API request runs inside a transaction that first sets `app.user_id` and `app.role` (read back by the functions `app_user_id()` and `app_role()`). The policies:
- **SELECT**: you can see an entry if it is yours, if you are a moderator or admin, or if its owner's diary is not private.
- **UPDATE / DELETE**: only your own entries; moderators and admins can also delete (to remove reported reviews).

Because this lives in the database, even a bug in an API query cannot leak a private diary.

### 3.5 Indexes
- GIN trigram indexes for fuzzy search: book titles, author names, genre names, usernames.
- B-tree indexes on every foreign key used in joins (`idx_diary_user`, `idx_diary_book`, `idx_book_author_book`, `idx_comment_entry`…), on `(user_id, date_read)` for diaries by year, and a partial index on pending outbox rows (`WHERE done_at IS NULL`) and open reports.

### 3.6 Mood tags (`tag` / `book_tag`)
Migration [005_mood_tags.sql](../backend/db/migrations/005_mood_tags.sql) fills the ER diagram's tag tables:
- **Rules as data**: `mood_rule` holds, for each mood, an array of genres and a regular expression for the description. For example, Dark = Horror, Gothic, Dystopian… or words such as *haunting*, *sinister*, *bleak* (`\m…\M` word boundaries, `~*` case-insensitive).
- **`tag_book_moods(book_id)`**: a PL/pgSQL function that deletes a book's mood tags and re-inserts them from the rules (`EXISTS` on `book_genre` OR the regex). Called with no argument, it re-tags the whole catalogue in about 9 seconds.
- **Triggers**: `book_genre_moods` (after a genre is added to a book) and `book_description_moods` (after a description changes) re-tag that book, so imported and admin-edited books get moods automatically.
- **Queries**: Explore filters with `EXISTS (SELECT 1 FROM book_tag JOIN tag … WHERE t.name = :mood)`; `GET /discover/moods` counts books per mood with `GROUP BY`.

### 3.7 Roles
| Role | Used by | Rights |
|---|---|---|
| `postgres` | you, for setup and pgAdmin | superuser |
| `booklog_app` | the API | owns the app tables, subject to RLS, not a superuser |
| `booklog_reports` | refreshing materialized views | read access for reports |

---

## 4. Neo4j: the social graph

Neo4j holds a copy of two things from PostgreSQL, kept in sync by the outbox worker:

```
(:User {user_id, username})-[:FOLLOWS]->(:User)
(:User)-[:RATED {rating, liked}]->(:Book {book_id, title})
```

Uniqueness constraints on `User.user_id` and `Book.book_id`. Queries (in [graph.py](../backend/app/graph.py)):

| Feature | Cypher idea |
|---|---|
| People you may know | `(me)-[:FOLLOWS]->(friend)-[:FOLLOWS]->(fof)` where you don't follow `fof` yet, ranked by mutual friends |
| Steps apart | `shortestPath((a)-[:FOLLOWS*..6]-(b))` |
| Taste match | books both users `RATED`, comparing ratings |
| Similar-taste recommendations | users who rated your books highly → other books they rated highly |

Neo4j can always be rebuilt from PostgreSQL with `backend/scripts/sync_neo4j.py`, so it is never the only copy of anything.

---

## 5. MongoDB: documents and logs

Database `booklog` (local `mongodb://localhost:27017`, or Atlas). Indexes are created at API start-up.

| Collection | One document is… | Fields | Used for |
|---|---|---|---|
| `activity_logs` | one view, click, search or take | `type`, `user_id`, `book_id`, `query`, `source`, `ts` | Trending books (aggregation pipeline over the last 7 days, clicks count double) |
| `book_takes` | one take on a book | `book_id`, `user_id`, `username`, `text`, `vibe`, `likes` (array of user IDs), `created_at` | Flips and book pages |
| `messages` | one direct message | `thread` ("smallerId:largerId"), `from`, `to`, `from_username`, `text`, `book` (optional shared book card), `read`, `created_at` | Messages page and unread badge |
| `chat_sessions` | one chatbot conversation | `user_id`, `title`, `messages` (array of role / content / books), `updated_at` | Book assistant history |
| `saved_recommendations` | one reader's cached recommendations | `user_id`, `items`, `created_at` | Expires automatically after 1 hour (TTL index) |
| `presence` | when a reader was last active | `user_id`, `ts` | "Online now" |
| `user_state` | small per-reader settings | `user_id`, `notifications_seen_at` | Notification badge |

When an account is deleted, PostgreSQL queues a `delete_user` operation for MongoDB in the outbox, and the worker removes that reader's documents.

---

## 6. Firebase: sign-in only

1. The browser signs in with Google through Firebase and gets a short-lived **ID token**.
2. Every API call sends it as `Authorization: Bearer <token>`.
3. The API verifies it with the Firebase Admin SDK, using the service-account key `booklog-firebase-key.json` (never committed), and looks up the matching `users.firebase_uid` in PostgreSQL.

Firebase stores only the Google login. Everything else is in our three databases.

---

## 7. Keeping the databases consistent

Writing to three databases in one request could leave them out of step if one write fails. BookLog uses the **transactional outbox** pattern:

1. A trigger writes the change into `sync_outbox` in the **same PostgreSQL transaction** as the change itself. Either both are saved, or neither is.
2. A background worker inside the API (`sync_worker.py`) reads pending rows in order, in batches of 200, and applies them to Neo4j or MongoDB.
3. On failure it records `attempts` and `last_error` and retries later. Nothing is lost while Neo4j is down.
4. Admin → Reports shows pending rows and errors, and has a "run sync now" button.

Outbox operations: `upsert_user`, `follow`, `unfollow`, `refresh_read` (a rating changed), `delete_user` (Neo4j and MongoDB).

---

## 8. Admin analytics and the SQL behind them

Admin → **Analytics** answers questions like "which book was most read last month?" for any time frame: 7 days, 30 days, 90 days, 12 months, this year, last year, all time or custom dates. Every number is compared with the same-length period just before it.

A diary entry counts on the day the book was read (`date_read`), or the day it was logged if no date was given: `COALESCE(d.date_read, d.created_at::date)`.

| Section | What it shows | SQL features |
|---|---|---|
| Headline numbers | books logged, active readers, different books, pages, average rating, reviews, new readers, each with % change | `count(*) FILTER (WHERE …)` to count both periods in one scan, scalar subqueries |
| Reading activity over time | per day / week / month: books, readers, reviews, sign-ups | CTE + `generate_series` so empty periods show as 0, `date_trunc`, `LEFT JOIN` |
| Most read books | ranked by distinct readers, then logs | `DENSE_RANK() OVER (…)` window function |
| Highest rated books | average rating, minimum 2 ratings | `HAVING count(rating) >= 2` |
| Genres read | logs, readers, rating and share of total | `sum(count(*)) OVER ()` window for percentages; many-to-many joins |
| Rising and falling genres | this period vs. previous | CTE, `FILTER`, `NULLIF` to avoid dividing by zero |
| Most read authors | logs, books, readers | join through `book_author` |
| Rating distribution | how many of each half-star | `generate_series(0.5, 5.0, 0.5)` + `LEFT JOIN` |
| Which day people finish books | Monday … Sunday | `EXTRACT(ISODOW …)` |
| Most active readers | books, pages, reviews, re-reads | `RANK()`; re-reads = `count(*) - count(DISTINCT book_id)` |
| When the books were written | by decade | `CASE` buckets |
| Book length | short / medium / long / epic | `CASE` buckets ordered by `min(page_count)` |
| Most wanted books | current shelves | `FILTER` per shelf status |
| Engagement funnel | signed up → logged → reviewed → made a list → follows someone | scalar subqueries + `UNION ALL` |
| Reading goals | progress and status (completed / on track / behind) | `CASE` with day-of-year arithmetic |
| Most followed readers | followers, following, lists | `LEFT JOIN` + correlated subqueries |

Every section has an **SQL** button that shows the exact query and the parameter values it ran with, and a **CSV** button that downloads its rows. **How these are computed** lists every query and explains each SQL feature. The queries are in [insights_service.py](../backend/app/services/insights_service.py) and run as the admin session, so (through row-level security) private diaries are included in the totals.

For a live database demo in a terminal, `backend/db/demo_queries.sql` walks through joins, aggregation, fuzzy search, constraints, triggers, row-level security, the outbox, materialized views and cascades, then rolls everything back.

---

## 9. Demo data

A fresh install has the full catalogue but **no users or activity** (see [database/README.md](../database/README.md)). Demo data is optional: `setup.bat` asks (default no), or you run the script yourself.

`backend/scripts/seed_demo_users.py` adds **16 demo readers** with about 18 months of history, so every page and chart has data:

`aarav_reads`, `diya_bookworm`, `kabir_pages`, `meera_writes` (private), `rohan_scifi`, `ananya_lit`, `ishaan_history`, `tara_fantasy`, `vikram_horror` (private), `neha_selfhelp`, `mayur_m`, `madhur_sikarwar`, `abhiram_k`, `avyay_t`, `aryan_chauhan`, `samarjeet` (private).

| Database | What gets created |
|---|---|
| PostgreSQL | ~560 diary entries (ratings, ~280 reviews, likes, re-reads), shelves, reading goals for last year and this year, favourite genres, followed authors, ~85 follows (and some follows of real accounts), ~28 ranked lists, review and list likes, ~210 comments, 3 open review reports |
| MongoDB | ~50 takes with likes, ~45 direct messages between mutual followers, ~600 view / click / search events (so Trending works), recent presence |
| Neo4j | filled by the sync worker from the outbox (follows and ratings) |

The demo accounts have `firebase_uid = 'demo_<username>'`, so nobody can sign in as them. The data is the same every run (fixed random seed).

```powershell
backend\venv\Scripts\python.exe backend\scripts\seed_demo_users.py           # add (skips if they exist)
backend\venv\Scripts\python.exe backend\scripts\seed_demo_users.py --reset   # delete and add again
backend\venv\Scripts\python.exe backend\scripts\seed_demo_users.py --remove  # delete them and everything they made
```

`backend/scripts/fill_user.py <username>` gives a real account (after its first sign-in) about 30 diary entries, shelves, goals, two lists and a circle of demo readers who follow it back, plus takes and messages in MongoDB.

---

## 10. API reference

Interactive docs: http://localhost:8000/docs. "Signed in" means a Firebase token is required.

| Area | Endpoints |
|---|---|
| Health | `GET /health` |
| Catalogue | `GET /search`, `/genres`, `/languages`, `/books`, `/books/stats`, `/books/trending`, `/book/{title}`, `/book/{title}/similar`, `/books/{id}/reviews`, `POST /activity/click` |
| Discover | `GET /discover/browse` (filters incl. `mood`), `/discover/moods`, `/discover/genres`, `/discover/random`, `/discover/today`, `/discover/stats`, `/discover/authors`, `/discover/journal` |
| Authors | `GET /author/{name}`, `POST /author/follow`, `POST /author/unfollow`, `GET /me/followed-authors` |
| Diary and shelves | `POST /diary`, `PATCH`/`DELETE /diary/{id}`, `PUT`/`DELETE /shelves/{book_id}`, `GET`/`PUT /me/goal`, `DELETE /me/goal/{year}` |
| Reviews | `POST /reviews/{id}/like`, `GET`/`POST /reviews/{id}/comments`, `POST /reviews/{id}/report`, `DELETE /comments/{id}` |
| Lists | `GET`/`POST /lists`, `GET /lists/mine`, `GET`/`PATCH`/`DELETE /lists/{id}`, `POST /lists/{id}/books`, `DELETE /lists/{id}/books/{book_id}`, `PUT /lists/{id}/order`, `POST /lists/{id}/like`, `GET`/`POST /lists/{id}/comments` |
| Me | `GET`/`PATCH`/`DELETE /me`, `PUT /me/genres`, `GET /me/export`, `GET /me/pulse`, `GET /recommendations` |
| People | `GET /feed`, `/people/suggestions`, `/people/search`, `/people/reading-now`, `/books/{id}/readers-now`, `/users/{username}` (+ `/diary`, `/shelves`, `/lists`, `/goal`, `/followers`, `/following`, `/stats`), `POST`/`DELETE /users/{username}/follow` |
| Flips | `GET /flips`, `GET /books/{id}/takes`, `POST /takes`, `POST /takes/{id}/like`, `DELETE /takes/{id}` |
| Messages | `GET /messages`, `/messages/contacts`, `GET`/`POST /messages/{username}`, `POST /messages/{username}/read`, `GET /notifications`, `POST /notifications/seen` |
| Chatbot | `GET /chat/sessions`, `GET`/`DELETE /chat/sessions/{id}`, `POST /chat/messages` |
| Admin | `GET`/`POST /admin/books`, `GET`/`PUT`/`DELETE /admin/books/{id}`, same for `/admin/authors` and `/admin/genres`, `GET /admin/reports`, `POST /admin/reports/{id}/resolve`, `GET /admin/analytics`, `GET /admin/insights`, `GET /admin/audit`, `GET /admin/users`, `PUT /admin/users/{id}/role`, `POST /admin/sync/run` |
