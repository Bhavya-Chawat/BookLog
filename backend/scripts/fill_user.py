"""
Gives a real account some history for demos: diary entries with ratings and
reviews, shelves, a reading goal, two lists, favourite genres, and a circle
(follows both ways with the demo readers), plus takes and messages in MongoDB.

    python backend/scripts/fill_user.py bhavya_chawat
    python backend/scripts/fill_user.py bhavya_chawat --reset   # remove what this script added first

Run seed_demo_users.py first (the circle is made of the demo readers).
--reset deletes the user's diary, shelves, lists and goals, their follows with demo
readers, and their takes and demo-reader messages in MongoDB, then adds them again.
"""
import os
import random
import sys
from datetime import date, datetime, time, timedelta, timezone

import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))
sys.path.insert(0, HERE)
from seed_demo_users import COMMENTS, MESSAGES, REVIEWS, TAKES, mongo_db  # noqa: E402

TODAY = date.today()
NOW = datetime.now(timezone.utc)
rng = random.Random(7)
FAVS = ["Science Fiction", "Technology", "Fantasy", "Thriller", "Classic"]


def ts(d):
    return datetime.combine(d, time(rng.randint(8, 23), rng.randint(0, 59)), tzinfo=timezone.utc)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: fill_user.py <username> [--reset]")
    username = args[0]
    conn = psycopg2.connect(os.getenv("DATABASE_ADMIN_URL") or os.getenv("DATABASE_URL"))
    mdb = mongo_db()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if not row:
            sys.exit(f"No user called {username}. Sign in on the website once first.")
        me = row[0]
        cur.execute("SELECT user_id, username FROM users WHERE firebase_uid LIKE 'demo\\_%%' ORDER BY user_id")
        demo = cur.fetchall()
        if not demo:
            sys.exit("No demo readers yet. Run seed_demo_users.py first.")
        names = dict(demo)
        demo_ids = list(names)

        if "--reset" in sys.argv:
            cur.execute("DELETE FROM diary_entry WHERE user_id = %s", (me,))
            cur.execute("DELETE FROM shelf WHERE user_id = %s", (me,))
            cur.execute("DELETE FROM list WHERE user_id = %s", (me,))
            cur.execute("DELETE FROM reading_goal WHERE user_id = %s", (me,))
            cur.execute("DELETE FROM user_follow WHERE (follower_id = %s AND followee_id = ANY(%s)) "
                        "OR (followee_id = %s AND follower_id = ANY(%s))", (me, demo_ids, me, demo_ids))
            if mdb is not None:
                mdb.book_takes.delete_many({"user_id": me})
                mdb.messages.delete_many({"$or": [{"from": me, "to": {"$in": demo_ids}}, {"to": me, "from": {"$in": demo_ids}}]})
            print("Removed the earlier demo history.")

        cur.execute("SELECT count(*) FROM diary_entry WHERE user_id = %s", (me,))
        if cur.fetchone()[0] >= 10:
            print(f"{username} already has a diary. Use --reset to rebuild it.")
            return

        # Favourite genres
        for g in FAVS:
            cur.execute("INSERT INTO user_genre SELECT %s, genre_id FROM genre WHERE name = %s ON CONFLICT DO NOTHING", (me, g))

        # Popular books from the favourite genres
        cur.execute(
            """SELECT DISTINCT ON (b.book_id) b.book_id, b.avg_rating, b.ratings_count FROM book b
               JOIN book_genre bg USING (book_id) JOIN genre g USING (genre_id)
               WHERE g.name = ANY(%s) AND b.cover_url IS NOT NULL""",
            (FAVS,),
        )
        pool = sorted(cur.fetchall(), key=lambda r: -r[2])[:250]
        picks = rng.sample(pool[:120], 34)

        # Diary: ~30 books over the last 14 months
        read, loved = [], []
        for book_id, avg, _ in picks[:30]:
            d = TODAY - timedelta(days=rng.randint(0, 420))
            rating = min(5.0, max(1.0, round((float(avg or 3.9) + rng.gauss(0.2, 0.6)) * 2) / 2))
            review = rng.choice(REVIEWS[max(1, min(5, round(rating)))]) if rng.random() < 0.5 else None
            cur.execute(
                """INSERT INTO diary_entry (user_id, book_id, rating, review_text, date_read, is_liked, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING entry_id""",
                (me, book_id, rating, review, d, rating >= 4.5, ts(d)),
            )
            entry_id = cur.fetchone()[0]
            read.append(book_id)
            if rating >= 4:
                loved.append(book_id)
            if review:  # the circle likes and comments on the reviews
                for liker in rng.sample(demo_ids, rng.randint(1, 6)):
                    cur.execute("INSERT INTO review_like (user_id, entry_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (liker, entry_id))
                if rng.random() < 0.5:
                    cur.execute("INSERT INTO comment (user_id, comment_text, entry_id, created_at) VALUES (%s, %s, %s, %s)",
                                (rng.choice(demo_ids), rng.choice(COMMENTS), entry_id, ts(min(TODAY, d + timedelta(days=rng.randint(0, 5))))))

        # Shelves
        for i, (book_id, _, _) in enumerate(picks[30:34]):
            cur.execute("INSERT INTO shelf (user_id, book_id, status) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (me, book_id, "currently_reading" if i < 2 else "want_to_read"))
        for book_id, _, _ in rng.sample(pool[120:], 6):
            cur.execute("INSERT INTO shelf (user_id, book_id, status) VALUES (%s, %s, 'want_to_read') ON CONFLICT DO NOTHING", (me, book_id))

        # Goals (books_finished is filled in by the trigger)
        for year, target in ((TODAY.year - 1, 18), (TODAY.year, 30)):
            cur.execute("INSERT INTO reading_goal (user_id, year, target_books) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (me, year, target))

        # Lists
        for name, desc, books in (("Sci-fi that rewired my brain", "Big ideas, bigger worlds.", loved[:8]),
                                  ("Read these this semester", "Short enough to finish between exams.", read[8:15])):
            if len(books) < 3:
                continue
            cur.execute("INSERT INTO list (user_id, name, description, is_public) VALUES (%s, %s, %s, true) RETURNING list_id",
                        (me, name, desc))
            lid = cur.fetchone()[0]
            for pos, b in enumerate(books, 1):
                cur.execute("INSERT INTO list_book (list_id, book_id, position) VALUES (%s, %s, %s)", (lid, b, pos))
            for liker in rng.sample(demo_ids, rng.randint(3, 8)):
                cur.execute("INSERT INTO list_like (user_id, list_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (liker, lid))

        # Circle: follow 10 demo readers; 12 follow back
        for other in rng.sample(demo_ids, min(10, len(demo_ids))):
            cur.execute("INSERT INTO user_follow (follower_id, followee_id, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (me, other, ts(TODAY - timedelta(days=rng.randint(1, 200)))))
        for other in rng.sample(demo_ids, min(12, len(demo_ids))):
            cur.execute("INSERT INTO user_follow (follower_id, followee_id, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (other, me, ts(TODAY - timedelta(days=rng.randint(0, 200)))))

        # Follow authors of loved books
        cur.execute("""INSERT INTO author_follow (user_id, author_id)
                       SELECT DISTINCT %s, author_id FROM book_author WHERE book_id = ANY(%s) ON CONFLICT DO NOTHING""",
                    (me, loved[:5]))

        cur.execute("SELECT followee_id FROM user_follow WHERE follower_id = %s", (me,))
        following = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT follower_id FROM user_follow WHERE followee_id = %s", (me,))
        followers = {r[0] for r in cur.fetchall()}

    # MongoDB: takes and a few message threads
    takes = messages = 0
    if mdb is not None:
        docs = []
        for b in loved[:5]:
            vibe, text = rng.choice(TAKES)
            docs.append({"book_id": b, "user_id": me, "username": username, "text": text, "vibe": vibe,
                         "likes": rng.sample(demo_ids, rng.randint(1, 7)),
                         "created_at": NOW - timedelta(days=rng.uniform(0, 40))})
        if docs:
            mdb.book_takes.insert_many(docs)
            takes = len(docs)
        connected = sorted(following | followers)
        docs = []
        for other in rng.sample(connected, min(5, len(connected))):
            a, b = min(me, other), max(me, other)
            start = NOW - timedelta(days=rng.uniform(0, 20))
            n = rng.randint(3, 6)
            for k in range(n):
                sender = other if k % 2 == 0 else me
                at = start + timedelta(minutes=k * rng.randint(3, 60))
                docs.append({"thread": f"{a}:{b}", "from": sender, "to": me if sender == other else other,
                             "from_username": names.get(sender, username), "text": rng.choice(MESSAGES), "book": None,
                             # the last message in two threads stays unread, so the badge shows
                             "read": not (k == n - 1 and sender == other and len(docs) < 12), "created_at": min(at, NOW)})
        if docs:
            mdb.messages.insert_many(docs)
            messages = len(docs)

    print(f"{username}: {len(read)} books logged, {len(following)} following, {len(followers)} followers, "
          f"2 lists, goals set, {takes} takes, {messages} messages.")


if __name__ == "__main__":
    main()
