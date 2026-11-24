# Setting up BookLog on Windows

This guide takes a fresh clone of the repository to a running BookLog on your own computer.
It takes about 20 minutes, most of it installing programs.

**What you get:** the full catalogue — 24,884 books, 16,156 authors, 7,770 publishers,
76 genres and 13 moods (42,744 mood tags) — with **no users and no activity**. The first
person to sign in is user number 1. Demo readers are optional (step 8).

> macOS or Linux? See *Setup on macOS / Linux* in the [README](../README.md#setup-on-macos--linux).

---

## 1. Install these programs

| Program | Version | Notes |
|---|---|---|
| [Git](https://git-scm.com/download/win) | any | To clone the repository |
| [Python](https://www.python.org/downloads/) | 3.10 or newer | On the first installer screen, tick **Add python.exe to PATH** |
| [Node.js](https://nodejs.org/) | 20.19+ or 22.12+ (take the LTS) | npm comes with it |
| [PostgreSQL](https://www.postgresql.org/download/windows/) | 15 or newer | Use the EDB installer. **Write down the password you choose for the `postgres` user.** Keep port 5432. Stack Builder is not needed. pgAdmin comes with it. |
| [Neo4j Desktop](https://neo4j.com/download/) | 5.x database | Holds the social graph |
| [MongoDB Community Server](https://www.mongodb.com/try/download/community) | 6 or newer | Choose **Install MongoD as a Service**. Compass (optional) lets you browse the data. |

An [OpenAI API key](https://platform.openai.com/api-keys) is optional. Only the chatbot uses it.

After installing Python and Node.js, open a **new** terminal so it picks up the new PATH.

## 2. Clone the repository

```powershell
git clone https://github.com/Bhavya-Chawat/BookLog.git
```

```powershell
cd BookLog
```

(Use your fork's URL if you forked it.)

## 3. Create and start a Neo4j database

1. Open Neo4j Desktop and create a new local instance (any name, Neo4j 5).
2. Set a password for it and **write it down**. Setup asks for it.
3. Press **Start** and wait until it says *Running*.

It listens on `bolt://localhost:7687`. You don't need to create anything inside it: setup fills
the graph from PostgreSQL.

## 4. Add the Firebase key (for sign-in)

BookLog signs people in with Google through Firebase. The website half of the Firebase config
is already in `frontend/src/firebase.js`. The API half is a **service-account key**, a secret
file that is never committed. Without it the site still opens and you can browse every book,
but nobody can sign in.

Pick one:

**A. Use the project's Firebase.** Ask the project owners for the key file. Save it in the
repository root (next to `setup.bat`) as **`booklog-firebase-key.json`**.

**B. Use your own Firebase project.**
1. Go to [console.firebase.google.com](https://console.firebase.google.com) and create a project.
2. *Build → Authentication → Get started → Sign-in method → Google → Enable*.
3. *Project settings → General → Your apps → Add app → Web*. Copy the `firebaseConfig`
   values into `frontend/src/firebase.js`.
4. *Project settings → Service accounts → Generate new private key*. Rename the downloaded
   file to `booklog-firebase-key.json` and put it in the repository root.

`localhost` is an authorised domain by default, so sign-in works locally straight away.

> Never commit the key file or paste its contents anywhere. It is already in `.gitignore`.

## 5. Run setup

Double-click **`setup.bat`** in the repository root. It asks for:

| Question | What to enter |
|---|---|
| Neo4j password | The password from step 3 |
| MongoDB URL | Press Enter for a local MongoDB (`mongodb://localhost:27017`), or paste a MongoDB Atlas `mongodb+srv://` URL |
| OpenAI API key | Paste it, or press Enter to skip |
| `postgres` password | The password from installing PostgreSQL (typing is hidden) |
| Add 16 demo readers? | **N** (the default) for an empty site, **Y** for sample readers (see step 8) |

Your answers are saved in `backend/.env`, which is never committed. Setup then:

1. checks that Python, Node.js and PostgreSQL are installed and stops if one is missing;
2. installs the Python packages into `backend/venv` and the npm packages into `frontend/node_modules`;
3. if there is **no `booklog` database yet**, unzips `database/booklog-database.zip`, creates the
   database and restores the catalogue, creates the `booklog_app` and `booklog_reports` roles
   (migrations 003 and 004) and starts every id counter at 1;
4. gives `booklog_app` a random password and writes it into `DATABASE_URL` in `backend/.env`;
5. rebuilds the Neo4j graph from PostgreSQL;
6. checks MongoDB, the Firebase key and the OpenAI key;
7. ends with **All set**, or a numbered list of what is still missing.

Fix anything on that list and run `setup.bat` again. **Running setup again is safe.** It only asks
for values that are still empty, and when the `booklog` database already exists it does not
restore anything and does not touch its users or activity.

## 6. Start BookLog

Double-click **`run.bat`**. Make sure your Neo4j instance is running first. Two windows open:

| Window | Address |
|---|---|
| BookLog API | http://localhost:8000 (interactive docs at http://localhost:8000/docs) |
| BookLog Web | http://localhost:5173 |

Your browser opens both. Open http://localhost:8000/health. It should show `true` for
`postgres`, `neo4j` and `mongodb`. Close the two windows to stop BookLog.

## 7. Sign in and make yourself an admin

1. On http://localhost:5173, sign in with Google and pick a username.
2. In a terminal in the repository root, run:

   ```powershell
   backend\venv\Scripts\python.exe backend\scripts\make_admin.py your_username
   ```

3. Reload the website. **Admin** now appears in the menu: catalogue editing, moderation,
   audit log, roles, sync status and Analytics.

`make_admin.py some_user moderator` makes someone a moderator; `... reader` takes the role away.

## 8. Optional: demo data

A fresh install has no readers, so the feed, People suggestions and Admin → Analytics are
empty until people use the site. To fill them for a demo:

```powershell
backend\venv\Scripts\python.exe backend\scripts\seed_demo_users.py
```

This adds 16 demo readers with about 18 months of diaries, reviews, shelves, goals, lists,
follows, likes, comments, takes and messages. Demo accounts can't sign in; they exist to be
looked at and followed.

To give **your own account** a history and a circle of those demo readers:

```powershell
backend\venv\Scripts\python.exe backend\scripts\fill_user.py your_username
```

To remove the demo readers and everything they made (real accounts are not touched):

```powershell
backend\venv\Scripts\python.exe backend\scripts\seed_demo_users.py --remove
```

## Checking it worked

| Check | Expected |
|---|---|
| http://localhost:8000/health | `postgres`, `neo4j` and `mongodb` are all `true` |
| Explore page | Books with covers. The mood chips (Dark, Cosy, Funny…) filter them. |
| Search `dune` | Results appear while you type |
| Sign in | Your avatar shows in the top right |
| pgAdmin → booklog → `users` table | Only the accounts that have signed in |

## Setup options

Run these from a PowerShell window in the repository root, when the defaults don't fit:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -DemoData
```

| Option | Effect |
|---|---|
| `-DemoData` | Add the demo readers without asking |
| `-SkipNeo4j` | Don't rebuild the Neo4j graph (for example, Neo4j isn't installed yet) |
| `-PgPort 5433` | PostgreSQL listens on a port other than 5432 |

## Starting again from an empty database

Setup never deletes a database. To go back to the empty catalogue, **which deletes every
account and all activity in it**, drop the database and run setup again:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\dropdb.exe" -U postgres booklog
```

Change `18` to your PostgreSQL version. Make a backup first if you want to keep anything
(see *Backup and restore* in the README). MongoDB keeps its takes and messages until you
delete the `booklog` database in Compass.

## Troubleshooting

| Problem | Fix |
|---|---|
| Setup says Python or Node.js is missing, but you installed it | Open a new terminal (or sign out and back in) so the new PATH applies. For Python, re-run the installer and tick *Add python.exe to PATH*. |
| *could not log in as postgres* | Wrong `postgres` password, or the PostgreSQL service is stopped. Start `postgresql-x64-<version>` in `services.msc` and run setup again. |
| *Neo4j is not running on localhost:7687* | Start the instance in Neo4j Desktop and run setup again. |
| *sync_neo4j.py failed* | `NEO4J_PASSWORD` in `backend/.env` doesn't match your Neo4j instance. Fix it and run setup again. |
| *MongoDB is not running on localhost:27017* | Start the **MongoDB** service in `services.msc`, or install MongoDB Community Server as a service. |
| `npm install failed` | Check your Node.js version (`node --version`; Vite 8 needs 20.19+ or 22.12+), then run setup again. |
| Sign-in works but every request is 401 | `booklog-firebase-key.json` is missing, or belongs to a different Firebase project than `frontend/src/firebase.js`. |
| *Admins and moderators only* on the Admin page | Run `make_admin.py` (step 7), then reload. |
| Chatbot says it isn't set up | Add `OPENAI_API_KEY` to `backend/.env` and restart the API window. |
| Port 8000 or 5173 is in use | Another program has it. Find it with `Get-NetTCPConnection -LocalPort 8000` and stop that process. |

## What setup writes, and where

| File / place | Contents | Committed? |
|---|---|---|
| `backend/.env` | `DATABASE_URL` (with the `booklog_app` password), Neo4j and MongoDB settings, OpenAI key | No |
| `booklog-firebase-key.json` | Firebase service-account key (you add it) | No |
| `backend/venv/`, `frontend/node_modules/` | Installed packages | No |
| `database/booklog.dump`, `database/booklog.sql` | Unzipped snapshot | No |
| PostgreSQL database `booklog` | The catalogue, then everything people do on the site | — |
| Neo4j | Users, follows and ratings, rebuilt from PostgreSQL | — |
| MongoDB database `booklog` | Takes, messages, chat history, activity logs | — |

[docs/FEATURES.md](FEATURES.md) explains what each database stores and why.
