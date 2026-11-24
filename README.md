# BookLog

A social book diary and recommendation system. Log books with ratings and reviews, keep shelves and ranked lists, follow other readers, swap takes and messages, get recommendations that explain themselves, and ask a chatbot for books in plain language. Admins get moderation tools and time-frame analytics that show the SQL behind every number.

*DBMS course project (CD252IA), Department of ISE, RV College of Engineering, by Archit Patil and Bhavya Chawat.*

**Stack:** PostgreSQL 15+ (main database) · Neo4j 5 (social graph) · MongoDB (documents and logs) · FastAPI (Python) · React 19 + Vite + Tailwind · Firebase Auth (Google sign-in) · OpenAI (chatbot)

## Documentation

| Document | What's in it |
|---|---|
| **This README** | What BookLog is, how to install and run it, the scripts, tests and backups |
| **[docs/SETUP.md](docs/SETUP.md)** | Step-by-step setup on Windows from a fresh clone, demo data, troubleshooting |
| **[docs/FEATURES.md](docs/FEATURES.md)** | Every feature in detail, what each database stores and why, triggers, row-level security, the sync outbox, the admin analytics SQL, demo data and the API list |
| [database/README.md](database/README.md) | The catalogue snapshot that `setup.bat` restores |
| http://localhost:8000/docs | Interactive API docs (while the API is running) |

## Features at a glance

- **Catalogue of ~24,900 books (1,390 in Technology)** with covers, authors, genres and publishers. Typo-tolerant live search (PostgreSQL `pg_trgm`) and a Ctrl+K palette.
- **Diary**: half-star ratings, reviews, likes and re-reads. **Shelves** (Want to Read, Reading Now), **yearly reading goal**, **ranked lists** you can re-order.
- **Social**: follow readers and authors, activity feed, people you may know, taste match % and steps apart (Neo4j), likes, comments, **direct messages**, notifications.
- **Flips**: swipe through books and leave short **takes** (MongoDB).
- **Moods**: every book is tagged Dark, Cosy, Funny, Tense, Inspiring… (rules + trigger in SQL), and Explore filters by mood.
- **Explore**, home page discovery, a reader quiz, and **Year in books** stats for every reader.
- **Recommendations** from five sources, each with a reason. A **chatbot** that can only suggest books that really exist in the database.
- **Admin**: catalogue editing, moderation, audit log, roles, sync status, and **Analytics** by time frame (most read books, genres, authors, readers, ratings, goals, funnel…) with a SQL button on every section.
- Privacy enforced **in the database**: private diaries use PostgreSQL row-level security.

Full details: [docs/FEATURES.md](docs/FEATURES.md).

## The three databases

| Database | Stores | Why |
|---|---|---|
| **PostgreSQL** (source of truth) | Books, authors, genres, users, diary, shelves, goals, lists, follows, likes, comments, reports, audit log, sync outbox | Transactions, constraints, triggers, row-level security, materialized views |
| **Neo4j** | `(:User)-[:FOLLOWS]->(:User)` and `(:User)-[:RATED]->(:Book)` | Friends of friends, shortest paths, readers with similar taste |
| **MongoDB** | Takes, direct messages, chatbot conversations, activity logs, cached recommendations, presence | Document-shaped and high-volume data, automatic expiry (TTL) |

PostgreSQL triggers write every follow, rating and account deletion into a `sync_outbox` table in the same transaction, and a background worker in the API copies them to Neo4j and MongoDB (see [section 7 of the docs](docs/FEATURES.md#7-keeping-the-databases-consistent)). If Neo4j or MongoDB is down, the rest of the app keeps working.

## Repository layout

```
BookLog/
├── setup.bat / setup.ps1        setup on Windows from a fresh clone (safe to re-run)
├── run.bat                      start the API and the website
├── booklog-firebase-key.json    Firebase service-account key (you add it; never committed)
├── docs/
│   ├── SETUP.md                 setup guide
│   └── FEATURES.md              features and databases, in detail
├── data/                        source data
│   ├── data.csv                         original catalogue
│   ├── master_curated_books_universe_180.csv   curated classics (corrected)
│   ├── master_curated_books_universe.csv       earlier version of the curated list
│   └── curated_books_fix.json           Open Library data used to correct the curated books
├── database/                    catalogue snapshot restored by setup (booklog-database.zip, no users)
├── backend/
│   ├── .env.example             copy to .env and fill in
│   ├── requirements.txt
│   ├── app/                     the FastAPI application
│   │   ├── main.py              app, CORS, /health, start-up (indexes, sync worker)
│   │   ├── auth.py, deps.py     Firebase token check, roles, current viewer
│   │   ├── database.py          PostgreSQL pool; sets app.user_id / app.role for RLS
│   │   ├── graph.py             Neo4j queries
│   │   ├── mongo.py             MongoDB collections and helpers
│   │   ├── sync_worker.py       outbox worker (PostgreSQL → Neo4j / MongoDB)
│   │   ├── routes/              HTTP endpoints
│   │   └── services/            the logic and SQL (book, discover, diary, list, social,
│   │                            user, reels, chat, admin, insights = admin analytics)
│   ├── db/                      SQL only
│   │   ├── schema.sql           base schema (the ER diagram)
│   │   ├── migrations/          002 phase 2 (tables, triggers, RLS, views), 003 app role, 004 report role,
│   │   │                        005 mood tags (TAG / BOOK_TAG, rules, trigger)
│   │   └── demo_queries.sql     live database demo for presentations
│   ├── scripts/                 every runnable script (see the table below)
│   └── tests/test_api.py        end-to-end API test (100 checks)
└── frontend/
    └── src/
        ├── pages/               one file per page (Home, Explore, Flips, Book, Library, Lists,
        │                        Feed, People, Profile, Stats, Messages, Chat, Quiz, Settings, Admin…)
        ├── components/          shared UI, modals, cards, AdminInsights (analytics tab)
        ├── contexts/            signed-in user
        ├── services/api.js      API client
        └── firebase.js          Firebase web config
```

## Setup on Windows

**Full step-by-step guide: [docs/SETUP.md](docs/SETUP.md).** In short:

1. Install Python 3.10+, Node.js 20.19+ (LTS), PostgreSQL 15+, Neo4j Desktop and MongoDB Community Server. Start a Neo4j instance.
2. Put the Firebase service-account key in the repo root as `booklog-firebase-key.json` (or use your own Firebase project; see the guide).
3. Double-click **`setup.bat`**. It asks for your Neo4j password, MongoDB URL, OpenAI key (optional) and `postgres` password, installs the packages, restores the catalogue (24,884 books, 16,156 authors, mood tags) **with no users or activity**, creates the `booklog_app` role and rebuilds Neo4j. If a `booklog` database already exists it is left exactly as it is. Safe to re-run.
4. Double-click **`run.bat`**: the API on http://localhost:8000 and the website on http://localhost:5173. http://localhost:8000/health should show all three databases `true`.

**Make yourself an admin.** Sign in on the website once, then:

```powershell
backend\venv\Scripts\python.exe backend\scripts\make_admin.py your_username
```

Reload the site and the **Admin** page appears in the menu. For sample readers, see *Demo data* in the guide.

### Looking at the data
- **PostgreSQL**: in pgAdmin, open *Servers → PostgreSQL → Databases → booklog → Schemas → public → Tables*. Right-click a table → *View/Edit Data*, or use *Tools → Query Tool* for SQL.
- **MongoDB**: in Compass, connect to `mongodb://localhost:27017` and open the `booklog` database.
- **Neo4j**: in Neo4j Desktop, open the instance with *Neo4j Browser* and run `MATCH (u:User)-[r]->(x) RETURN u, r, x LIMIT 100`.

## Scripts

Everything runnable lives in `backend/scripts/`. Run the scripts from the repo root with the project's Python (`backend\venv\Scripts\python.exe` on Windows, `backend/venv/bin/python` on macOS and Linux). They read `backend/.env`.

| Script | What it does | When you need it |
|---|---|---|
| `make_admin.py <username> [role]` | Makes an account admin (or `moderator` / `reader`) | After you first sign in |
| `seed_demo_users.py` | Adds 16 demo readers with ~18 months of activity in PostgreSQL and MongoDB. `--reset` rebuilds them, `--remove` deletes them (real accounts are never touched). | Optional; setup asks (default no) |
| `fill_user.py <username>` | Gives a real account a demo history: ~30 diary entries, shelves, goals, 2 lists, a circle of demo readers (both ways), takes and messages. `--reset` rebuilds it. | Before a demo, after signing in once |
| `sync_neo4j.py` | Rebuilds the whole Neo4j graph from PostgreSQL | After restoring a backup, or if Neo4j was wiped |
| `fix_curated_books.py` | `apply` corrects the 178 curated classics (real authors, years, descriptions) from `data/curated_books_fix.json`; `fetch` re-downloads from Open Library; `csv` rewrites the CSV | Only for a database built with `seed_from_csv.py`; the snapshot is already corrected |
| `seed_from_csv.py` | **Drops and recreates** the database schema, runs the migrations and loads the CSVs in `data/` | Building the database from scratch instead of the snapshot |
| `import_openlibrary.py` | Adds books from Open Library across ~130 subjects (cached in `backend/scripts/.openlibrary_cache/`). `--subjects computer_science,machine_learning` limits it to some subjects; `--cache-only` uses only what is already downloaded | Building from scratch |
| `backfill_openlibrary.py` | Fills in descriptions, author bios and photos an import skipped (`--wikipedia` falls back to Wikipedia summaries) | Building from scratch |
| `migrate_from_neo4j.py` | One-time import of users and ratings from the old Neo4j-only version | Historical |
| `backup.sh` / `restore.sh` | Back up / restore PostgreSQL (macOS and Linux shells) | See *Backup and restore* |

Example:

```powershell
backend\venv\Scripts\python.exe backend\scripts\seed_demo_users.py --reset
```

`seed_from_csv.py`, `import_openlibrary.py` and `backfill_openlibrary.py` need a superuser connection: set `DATABASE_ADMIN_URL=postgresql://postgres:<password>@localhost:5432/booklog` in `backend/.env`.

## Tests

The end-to-end test acts as several temporary users (Firebase is replaced by a test header), checks 100 things across all three databases and deletes its users at the end. It runs against a **copy** of the database, so your real data is untouched.

```powershell
New-Item -ItemType Directory -Force backups | Out-Null; & "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -Fc -f backups\booklog_test.dump booklog
```

```powershell
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres booklog_test
```

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U postgres --no-owner -d booklog_test backups\booklog_test.dump
```

Then run it with `DATABASE_URL` pointing at `booklog_test` (same as in `.env`, with `/booklog_test` at the end):

```powershell
$env:DATABASE_URL = "postgresql://booklog_app:<password>@localhost:5432/booklog_test"; backend\venv\Scripts\python.exe backend\tests\test_api.py
```

It should end with `ALL 100 CHECKS PASSED`. The test expects a database without the demo readers. If you copied it after seeding, remove them first with `seed_demo_users.py --remove --no-mongo <test database URL>`.

**Live database demo** for presentations (joins, aggregation, fuzzy search, constraints, triggers, RLS, outbox, materialized views, cascades; rolls everything back):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d booklog -f backend\db\demo_queries.sql
```

## Backup and restore

**Windows:**

```powershell
New-Item -ItemType Directory -Force backups | Out-Null; & "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -Fc --no-owner --no-privileges -f backups\booklog.dump booklog
```

To restore on another computer, create the `booklog` database there and restore with `pg_restore --no-owner --no-privileges -d booklog <file>`, then run migrations 003 and 004 (`psql -f backend\db\migrations\003_app_role.sql`, same for 004). (`setup.bat` only restores the catalogue snapshot from the zip, never a backup.) Use `-f` with a file, as above; piping `pg_dump` output through PowerShell corrupts non-English text.

**macOS / Linux:** `sh backend/scripts/backup.sh` writes `backups/booklog-<date>.dump`; `sh backend/scripts/restore.sh <file>` restores it, re-creates the roles and rebuilds Neo4j.

Neo4j never needs a backup, because it is rebuilt from PostgreSQL. MongoDB holds takes, messages and chat history; back it up with `mongodump` (or Compass export) if you need them.

## Setup on macOS / Linux

```bash
brew install postgresql@15 neo4j && brew tap mongodb/brew && brew install mongodb-community
```

```bash
brew services start postgresql@15 && brew services start neo4j && brew services start mongodb-community
```

Set a Neo4j password before its first start with `neo4j-admin dbms set-initial-password <password>`. Then:

```bash
cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt && cp .env.example .env
```

Fill in `backend/.env`, then unzip and restore the catalogue snapshot (no users):

```bash
unzip database/booklog-database.zip -d database/ && sh backend/scripts/restore.sh database/booklog.dump
```

Optional demo readers: `backend/venv/bin/python backend/scripts/seed_demo_users.py`.

```bash
cd backend && venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `/health` shows `"neo4j": false` | Start the instance in Neo4j Desktop; check `NEO4J_PASSWORD` in `backend/.env`. |
| `/health` shows `"mongodb": false` | Start the **MongoDB** Windows service (`services.msc`), or check `MONGO_URL`. |
| API window says port 8000 is in use | Another program is on port 8000. Find it with `Get-NetTCPConnection -LocalPort 8000` and stop that process. |
| Sign-in works but every request is 401 | `booklog-firebase-key.json` is missing from the repo root, or belongs to a different Firebase project than `frontend/src/firebase.js`. |
| Chatbot says it isn't set up | Add `OPENAI_API_KEY` to `backend/.env` and restart the API. |
| Admin page says "Admins and moderators only" | Run `make_admin.py` (see above), then reload. |
| Demo readers not in the People suggestions | The sync worker copies them to Neo4j while the API runs; or run `sync_neo4j.py`. |

## Security notes

Never commit `backend/.env` (database, Neo4j and OpenAI secrets) or `booklog-firebase-key.json`. Both are in `.gitignore`. Each person keeps their own copy.

## Design

"Dog-eared": cream paper, one tomato red for type, tall condensed caps (Bayon) and a small uppercase grotesk (Inter Tight), with pink and sky-blue sections, plus a night-reading mode. The mascots are original line-drawn **book-dogs** (`frontend/src/components/Dogs.jsx`): books whose ears are hardcover boards and whose leash is the ribbon bookmark. Motion includes CSS 3D books, masked word reveals and smooth scrolling, and everything respects `prefers-reduced-motion`.
