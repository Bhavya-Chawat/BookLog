"""
Adds 16 demo readers with about 18 months of realistic activity, so feeds,
profiles and the admin analytics have something to show.

PostgreSQL: diary entries (ratings, reviews, likes, re-reads), shelves, reading
goals, favourite genres, followed authors, follows, ranked lists, review and
list likes, comments and a few open review reports.
MongoDB:    book takes (Flips), direct messages, view/click/search activity
(drives Trending) and "last seen" presence.
Neo4j:      filled automatically. The follows and ratings go into the sync
outbox and the API's worker copies them over (or run sync_neo4j.py).

    python backend/scripts/seed_demo_users.py            # add the demo readers (skips if they exist)
    python backend/scripts/seed_demo_users.py --reset    # delete them (and everything they made), then add again
    python backend/scripts/seed_demo_users.py --remove   # only delete them
    python backend/scripts/seed_demo_users.py --reset --no-mongo postgresql://...   # another database, PostgreSQL only

Demo accounts have firebase_uid 'demo_<username>', so nobody can sign in as them.
Rows go through the normal triggers: book ratings, reading goals, the audit log
and the sync outbox.
"""
import os
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone

import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))

TODAY = date.today()
NOW = datetime.now(timezone.utc)
rng = random.Random(42)  # same data every run

# username, bio, favourite genres, books per month (rough), private diary, months since joining
READERS = [
    ("aarav_reads", "Engineering student. Sci-fi on the metro.", ["Science Fiction", "Dystopian", "Classic"], 3.0, False, 18),
    ("diya_bookworm", "Romance and historical fiction, with chai.", ["Romance", "Historical Fiction", "Literary Fiction"], 4.0, False, 17),
    ("kabir_pages", "Thrillers, mysteries, anything with a twist.", ["Thriller", "Mystery", "Crime"], 3.5, False, 16),
    ("meera_writes", "Poetry and world literature. Slow reader.", ["Poetry", "World Literature", "Classic"], 1.5, True, 15),
    ("rohan_scifi", "If it has spaceships, I'm in.", ["Science Fiction", "Fantasy", "Space Opera"], 2.5, False, 14),
    ("ananya_lit", "Literature student. Annotating everything.", ["Classic", "Literary Fiction", "Philosophy"], 3.0, False, 12),
    ("ishaan_history", "History, biographies and big ideas.", ["History", "Biography", "Science"], 2.0, False, 11),
    ("tara_fantasy", "Dragons, maps and 800-page series.", ["Fantasy", "Young Adult", "Adventure"], 4.5, False, 9),
    ("vikram_horror", "Horror at midnight. Gothic at dawn.", ["Horror", "Gothic", "Paranormal"], 2.0, True, 7),
    ("neha_selfhelp", "Business, psychology and self-help notes.", ["Self-Help", "Psychology", "Business"], 1.5, False, 5),
    ("mayur_m", "Detective fiction and long train rides.", ["Detective Fiction", "Mystery", "Thriller"], 3.5, False, 18),
    ("madhur_sikarwar", "Epic fantasy, mythology and a bit of history.", ["Fantasy", "Mythology", "History"], 4.0, False, 16),
    ("abhiram_k", "Popular science, tech and the occasional memoir.", ["Popular Science", "Technology", "Memoir"], 2.5, False, 13),
    ("avyay_t", "Classics by day, graphic novels by night.", ["Classic", "Graphic Novels", "Humor"], 3.0, False, 10),
    ("aryan_chauhan", "War stories, thrillers and true crime.", ["War", "Thriller", "True Crime"], 2.5, False, 8),
    ("samarjeet", "Philosophy, economics and big questions.", ["Philosophy", "Economics", "Politics"], 2.0, True, 6),
]

REVIEWS = {
    5: ["An absolute favourite. I'll be thinking about this one for weeks.",
        "Perfect from start to finish. Recommending it to everyone.",
        "Beautifully written, I didn't want it to end.",
        "Stayed up till 3am to finish it. No regrets.",
        "One of those rare books that gets better on every page."],
    4: ["Really enjoyed it, a couple of slow chapters but worth it.",
        "Great characters and a strong ending.",
        "Smart and gripping. Nearly a five.",
        "The last hundred pages were brilliant.",
        "Took a while to get going, then I couldn't put it down."],
    3: ["Good, not great. The middle dragged a bit.",
        "Some brilliant moments, but uneven overall.",
        "Glad I read it, won't reread it.",
        "Liked the ideas more than the writing."],
    2: ["Couldn't connect with the characters.",
        "Interesting idea, weak execution.",
        "Far too long for what it had to say."],
    1: ["Not for me at all.", "Struggled to finish this one."],
}
LIST_NAMES = ["All-time favourites", "Perfect for a rainy weekend", "Books that changed my mind",
              "Start here if you're new to the genre", "Comfort reads", "Read these before you're 25",
              "Exam-season escapes", "Best of this year", "Underrated gems"]
COMMENTS = ["Totally agree!", "Adding this to my list.", "Hmm, I liked it more than you did.",
            "Great review.", "This list is gold.", "What should I read after this one?",
            "The ending though!", "You convinced me, starting it tonight.", "Fair points, but I loved it."]
TAKES = [
    ("must_read", "If you read one book this month, make it this one."),
    ("cried", "Chapter 20 wrecked me. Bring tissues."),
    ("mind_blown", "That twist rewired my brain."),
    ("slow_start", "Push through the first 50 pages, it is worth it."),
    ("comfort", "My go-to reread when the week is rough."),
    ("overrated", "Good, but not the masterpiece everyone says."),
    ("fun_fact", "The author wrote the first draft in under a year."),
    ("quote", "Underlined half of this. Every page has a line worth keeping."),
]
MESSAGES = ["Have you read this yet?", "Just finished it, we need to talk.", "Okay you were right about this one.",
            "What are you reading this week?", "Lending you my copy tomorrow.", "Your review made me pick it up!",
            "Book club on Sunday?", "That ending!!", "Adding it to my want-to-read.", "No spoilers please, I'm on chapter 12."]
SEARCHES = ["harry potter", "dune", "agatha christie", "best fantasy", "sapiens", "1984", "murakami", "sherlock",
            "atomic habits", "tolkien", "pride and prejudice", "stephen king", "brandon sanderson", "the alchemist"]


def rand_date(start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, max(0, (end - start).days)))


def ts(d: date) -> datetime:
    return datetime.combine(d, time(rng.randint(7, 23), rng.randint(0, 59)), tzinfo=timezone.utc)


def mongo_db():
    """The MongoDB database, or None if it isn't reachable (the PostgreSQL part still runs)."""
    try:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000, tz_aware=True)
        client.admin.command("ping")
        return client[os.getenv("MONGO_DB", "booklog")]
    except Exception as e:
        print(f"MongoDB not reachable, skipping takes/messages/activity ({e.__class__.__name__}).")
        return None


def remove(cur, mdb):
    cur.execute("SELECT user_id FROM users WHERE firebase_uid LIKE 'demo\\_%%'")
    ids = [r[0] for r in cur.fetchall()]
    if mdb is not None and ids:
        mdb.book_takes.delete_many({"user_id": {"$in": ids}})
        mdb.book_takes.update_many({}, {"$pull": {"likes": {"$in": ids}}})
        mdb.messages.delete_many({"$or": [{"from": {"$in": ids}}, {"to": {"$in": ids}}]})
        for coll in ("activity_logs", "presence", "user_state", "chat_sessions", "saved_recommendations"):
            mdb[coll].delete_many({"user_id": {"$in": ids}})
    cur.execute("DELETE FROM users WHERE firebase_uid LIKE 'demo\\_%%'")
    print(f"Removed {cur.rowcount} demo readers (and everything they made).")


def seed(cur, mdb):
    cur.execute("SELECT count(*) FROM users WHERE firebase_uid LIKE 'demo\\_%%'")
    if cur.fetchone()[0]:
        print("Demo readers already exist. Use --reset to recreate them.")
        return

    # Popular books per genre (with covers), so the demo looks real
    pool = {}
    for g in sorted({g for r in READERS for g in r[2]}):
        cur.execute(
            """
            SELECT b.book_id, b.avg_rating, b.page_count FROM book b
            JOIN book_genre bg USING (book_id) JOIN genre ge USING (genre_id)
            WHERE ge.name = %s AND b.cover_url IS NOT NULL
            ORDER BY b.ratings_count DESC LIMIT 120
            """,
            (g,),
        )
        pool[g] = cur.fetchall()
    cur.execute("SELECT book_id, avg_rating, page_count FROM book WHERE cover_url IS NOT NULL ORDER BY ratings_count DESC LIMIT 300")
    popular = cur.fetchall()

    user_ids, names, private_ids = {}, {}, set()
    read_by_user, loved_by_user, reviews = {}, {}, []
    for username, bio, favs, per_month, private, months in READERS:
        joined = TODAY - timedelta(days=int(months * 30.4) + rng.randint(0, 20))
        cur.execute(
            """
            INSERT INTO users (firebase_uid, friend_code, username, bio, is_private, created_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING user_id
            """,
            (f"demo_{username}", uuid.uuid4().hex[:8], username, bio, private, ts(joined)),
        )
        uid = user_ids[username] = cur.fetchone()[0]
        names[uid] = username
        if private:
            private_ids.add(uid)
        for g in favs:
            cur.execute("INSERT INTO user_genre SELECT %s, genre_id FROM genre WHERE name = %s ON CONFLICT DO NOTHING", (uid, g))

        # Diary: mostly favourite genres, some popular books, a few re-reads
        n = max(8, int(per_month * months * rng.uniform(0.9, 1.3)))
        read, loved = [], []
        for _ in range(n):
            source = pool[rng.choice(favs)] if rng.random() < 0.8 else popular
            source = source or popular
            # Skewed towards the most popular books, so readers overlap like real ones do
            book_id, avg, _pages = source[int(len(source) * rng.random() ** 3)]
            if book_id in read and rng.random() < 0.7:
                continue
            read.append(book_id)
            # Busier in Dec/Jan and the summer holidays
            d = rand_date(joined, TODAY)
            if d.month not in (12, 1, 5, 6) and rng.random() < 0.25:
                d = rand_date(joined, TODAY)
            base = float(avg or 3.8)
            rating = min(5.0, max(0.5, round((base + rng.gauss(0, 0.8)) * 2) / 2)) if rng.random() < 0.9 else None
            review = rng.choice(REVIEWS[max(1, min(5, round(rating)))]) if rating and rng.random() < 0.55 else None
            liked = bool(rating and rating >= 4 and rng.random() < 0.6)
            cur.execute(
                """
                INSERT INTO diary_entry (user_id, book_id, rating, review_text, date_read, is_liked, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING entry_id
                """,
                (uid, book_id, rating, review, d, liked, ts(d)),
            )
            eid = cur.fetchone()[0]
            if review:
                reviews.append((eid, uid, d))
            if rating and rating >= 4:
                loved.append(book_id)
        read_by_user[uid], loved_by_user[uid] = read, loved

        # Shelves: want to read + one or two in progress
        fav_pool = pool[favs[0]] or popular
        candidates = [b for b, _, _ in rng.sample(fav_pool, min(14, len(fav_pool))) if b not in read]
        reading_now = rng.randint(1, 2)
        for i, b in enumerate(candidates[:9]):
            status = "currently_reading" if i < reading_now else "want_to_read"
            cur.execute("INSERT INTO shelf (user_id, book_id, status, added_at) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (uid, b, status, ts(rand_date(TODAY - timedelta(days=120), TODAY))))

        # Reading goals (books_finished is filled in by the reading_goal_init trigger)
        for year in (TODAY.year - 1, TODAY.year):
            if joined.year <= year:
                cur.execute("INSERT INTO reading_goal (user_id, year, target_books) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (uid, year, max(6, round(per_month * 12 * rng.uniform(0.8, 1.4)))))

        # Follow the authors of a few favourite books
        if loved:
            cur.execute(
                """INSERT INTO author_follow (user_id, author_id, created_at)
                   SELECT DISTINCT %s, ba.author_id, %s FROM book_author ba WHERE ba.book_id = ANY(%s)
                   ON CONFLICT DO NOTHING""",
                (uid, ts(rand_date(joined, TODAY)), rng.sample(loved, min(4, len(loved)))),
            )

    ids = list(user_ids.values())
    cur.execute("SELECT user_id FROM users WHERE firebase_uid NOT LIKE 'demo\\_%%'")
    real = [r[0] for r in cur.fetchall()]

    # Follows: a small social graph, plus a few follows of the real accounts
    follows = set()
    for uid in ids:
        for other in rng.sample([i for i in ids if i != uid], rng.randint(3, 8)):
            follows.add((uid, other))
            cur.execute("INSERT INTO user_follow (follower_id, followee_id, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (uid, other, ts(rand_date(TODAY - timedelta(days=300), TODAY))))
        for other in real:
            if rng.random() < 0.4:
                cur.execute("INSERT INTO user_follow (follower_id, followee_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (uid, other))

    # Lists with ranked books
    list_ids = []
    for uid in ids:
        books = list(dict.fromkeys(read_by_user[uid]))
        for name in rng.sample(LIST_NAMES, rng.randint(1, 3)):
            if len(books) < 5:
                break
            created = ts(rand_date(TODAY - timedelta(days=240), TODAY))
            cur.execute("""INSERT INTO list (user_id, name, description, is_public, created_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING list_id""",
                        (uid, name, "A few books I keep recommending.", rng.random() < 0.85, created, created))
            lid = cur.fetchone()[0]
            list_ids.append((lid, uid))
            for pos, b in enumerate(rng.sample(books, min(len(books), rng.randint(5, 10))), 1):
                cur.execute("INSERT INTO list_book (list_id, book_id, position) VALUES (%s, %s, %s)", (lid, b, pos))

    # Likes and comments on reviews and lists
    comments = 0
    for eid, author, d in reviews:
        for liker in rng.sample(ids, rng.randint(0, 6)):
            if liker != author:
                cur.execute("INSERT INTO review_like (user_id, entry_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (liker, eid))
        for _ in range(rng.choice([0, 0, 0, 1, 1, 2])):
            cur.execute("INSERT INTO comment (user_id, comment_text, entry_id, created_at) VALUES (%s, %s, %s, %s)",
                        (rng.choice([i for i in ids if i != author]), rng.choice(COMMENTS), eid, ts(rand_date(d, TODAY))))
            comments += 1
    for lid, owner in list_ids:
        for liker in rng.sample(ids, rng.randint(0, 7)):
            if liker != owner:
                cur.execute("INSERT INTO list_like (user_id, list_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (liker, lid))
        for _ in range(rng.choice([0, 1, 1, 2])):
            cur.execute("INSERT INTO comment (user_id, comment_text, list_id) VALUES (%s, %s, %s)",
                        (rng.choice([i for i in ids if i != owner]), rng.choice(COMMENTS), lid))
            comments += 1

    # A few open reports so the moderation queue has something in it
    for eid, author, _d in rng.sample(reviews, min(3, len(reviews))):
        cur.execute("INSERT INTO review_report (entry_id, reporter_id, reason) VALUES (%s, %s, %s)",
                    (eid, rng.choice([i for i in ids if i != author]),
                     rng.choice(["Contains spoilers without a warning", "Off-topic", "Spam"])))

    for v in ("mv_most_read_books", "mv_active_users", "mv_genre_trends"):
        cur.execute(f"REFRESH MATERIALIZED VIEW {v}")

    mongo_counts = seed_mongo(mdb, ids, names, read_by_user, loved_by_user, follows) if mdb is not None else None

    cur.execute("SELECT count(*) FROM diary_entry WHERE user_id = ANY(%s)", (ids,))
    entries = cur.fetchone()[0]
    print(f"Added {len(ids)} demo readers: {entries} diary entries, {len(reviews)} reviews, {len(list_ids)} lists, "
          f"{len(follows)} follows, {comments} comments.")
    if mongo_counts:
        print("MongoDB: {takes} takes, {messages} messages, {activity} activity events.".format(**mongo_counts))


def seed_mongo(mdb, ids, names, read_by_user, loved_by_user, follows):
    """Takes, direct messages, activity logs and presence for the demo readers."""
    def when(days_back):
        return NOW - timedelta(days=rng.uniform(0, days_back), minutes=rng.randint(0, 600))

    takes = []
    for uid in ids:
        for b in rng.sample(loved_by_user[uid] or read_by_user[uid], min(rng.randint(2, 5), len(loved_by_user[uid] or read_by_user[uid]))):
            vibe, text = rng.choice(TAKES)
            takes.append({"book_id": b, "user_id": uid, "username": names[uid], "text": text, "vibe": vibe,
                          "likes": rng.sample([i for i in ids if i != uid], rng.randint(0, 6)), "created_at": when(90)})
    if takes:
        mdb.book_takes.insert_many(takes)

    # Messages only between readers who follow each other (the app's rule)
    messages = []
    mutual = sorted({tuple(sorted(p)) for p in follows if (p[1], p[0]) in follows})
    for a, b in rng.sample(mutual, min(14, len(mutual))):
        start = when(60)
        for k in range(rng.randint(2, 7)):
            sender, to = (a, b) if k % 2 == 0 else (b, a)
            at = start + timedelta(minutes=k * rng.randint(2, 90))
            messages.append({"thread": f"{a}:{b}", "from": sender, "to": to, "from_username": names[sender],
                             "text": rng.choice(MESSAGES), "book": None, "read": at < NOW - timedelta(hours=6),
                             "created_at": min(at, NOW)})
    if messages:
        mdb.messages.insert_many(messages)

    # Views, clicks and searches; weighted to the last two weeks so Trending has data
    activity = []
    for uid in ids:
        books = read_by_user[uid] + loved_by_user[uid] * 2
        for _ in range(rng.randint(25, 60)):
            kind = rng.choices(["view", "click", "search"], [6, 3, 1])[0]
            days = 14 if rng.random() < 0.6 else 60
            activity.append({"type": kind, "user_id": uid,
                             "book_id": None if kind == "search" else rng.choice(books),
                             "query": rng.choice(SEARCHES) if kind == "search" else None,
                             "source": None if kind == "search" else rng.choice(["home", "search", "explore", "flips", "list"]),
                             "ts": when(days)})
    if activity:
        mdb.activity_logs.insert_many(activity)

    for uid in rng.sample(ids, 6):
        mdb.presence.update_one({"user_id": uid}, {"$set": {"ts": when(2)}}, upsert=True)
    return {"takes": len(takes), "messages": len(messages), "activity": len(activity)}


def main():
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    urls = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = urls[0] if urls else (os.getenv("DATABASE_ADMIN_URL") or os.getenv("DATABASE_URL"))
    mdb = None if "--no-mongo" in flags else mongo_db()
    conn = psycopg2.connect(url)
    with conn, conn.cursor() as cur:
        if "--reset" in flags or "--remove" in flags:
            remove(cur, mdb)
        if "--remove" not in flags:
            seed(cur, mdb)
    conn.close()


if __name__ == "__main__":
    main()
