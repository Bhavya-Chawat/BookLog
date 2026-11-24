"""
Replaces the placeholder data in the curated CSV books with real data from Open Library.

master_curated_books_universe_180.csv had made-up values for 177 well-known books:
a template description ("... is a renowned literary classic widely regarded ..."),
fake ISBNs (9780000...), so no cover, random years, page counts and ratings, and
sometimes the wrong author (Infinite Jest by Daniel Defoe).

    python backend/scripts/fix_curated_books.py fetch   # look the books up -> curated_books_fix.json (needs internet)
    python backend/scripts/fix_curated_books.py apply   # update the database from curated_books_fix.json (offline)
    python backend/scripts/fix_curated_books.py csv     # rewrite the CSV from curated_books_fix.json

`apply` only touches books that still have the template description, so it is safe
to run more than once (setup.bat runs it after restoring the snapshot).
Book ids stay the same, so diaries, lists and shelves keep pointing at the same book.
"""
import csv
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import psycopg2
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))
sys.path.insert(0, HERE)
import import_openlibrary as ol  # noqa: E402  (cached Open Library fetch + cleaning helpers)
from curated_facts import FACTS, WRONG_MATCH  # noqa: E402

CSV_PATH = os.path.join(REPO_ROOT, "data", "master_curated_books_universe_180.csv")
FIX_PATH = os.path.join(REPO_ROOT, "data", "curated_books_fix.json")
TEMPLATE = "is a renowned literary classic widely regarded"
# Small fields only: isbn / publisher lists run to thousands of entries for classics and
# make Open Library time out. ISBN and publisher come from the cover edition instead.
FIELDS = ("key,title,author_name,author_key,first_publish_year,number_of_pages_median,"
          "ratings_average,ratings_count,cover_i,cover_edition_key,readinglog_count,edition_count")

# Titles Open Library files under a different name, or where the most-read exact
# match is the wrong book: title -> (search title, author)
OVERRIDES = {
    "1984": ("Nineteen Eighty-Four", "George Orwell"),
    "The Republic": ("The Republic", "Plato"),
}


# ---------------------------------------------------------------------
# fetch: CSV titles -> Open Library -> curated_books_fix.json
# ---------------------------------------------------------------------
def get(url):
    """Open Library is slow at times: longer timeout and more retries than the importer."""
    path = os.path.join(ol.CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if os.getenv("FIX_CACHE_ONLY"):
        return None
    os.makedirs(ol.CACHE_DIR, exist_ok=True)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ol.USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.load(resp)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            if getattr(e, "code", None) == 404:
                return None
            time.sleep(3 * (attempt + 1))
    return None


def search(title, author=None):
    params = {"title": title, "fields": FIELDS}
    if author:
        params.update(author=author, limit=50)  # few results: no need to sort
    else:
        params.update(limit=30, sort="readinglog")
    data = get(f"https://openlibrary.org/search.json?{urllib.parse.urlencode(params)}") or {}
    return data.get("docs", [])


def best_match(title, csv_author):
    search_title, author = OVERRIDES.get(title, (title, None))
    want = ol.norm_key(search_title)

    def exact(docs):
        return [d for d in docs if ol.norm_key(d.get("title")) == want and d.get("author_name")]

    def score(d):
        return (bool(d.get("cover_i")), d.get("readinglog_count") or 0, d.get("edition_count") or 0)

    # 1. the forced author, or the CSV author (right for most rows)
    for a in [author] if author else [csv_author]:
        docs = exact(search(search_title, a))
        if docs:
            return max(docs, key=score), "author"
    # 2. the CSV author was wrong: the most-read book with exactly this title
    docs = exact(search(search_title))
    if docs:
        return max(docs, key=score), "title"
    return None, "none"


def lookup(row):
    title, csv_author = row["Book:title"].strip(), row["Author:name"].split(",")[0].strip()
    doc, how = best_match(title, csv_author)
    if not doc:
        return title, None
    work = get(f"https://openlibrary.org{doc['key']}.json") or {}
    edition = get(f"https://openlibrary.org/books/{doc['cover_edition_key']}.json") if doc.get("cover_edition_key") else None
    edition = edition or {}
    year = doc.get("first_publish_year")
    pages = doc.get("number_of_pages_median")
    authors = doc["author_name"][:3]
    publisher = next((p.strip() for p in edition.get("publishers", []) if p and len(p.strip()) <= 200), None)
    return title, {
        "title": title,
        "match": how,
        "ol_key": doc["key"],
        "ol_title": doc.get("title"),
        "authors": authors,
        "author_keys": doc.get("author_key", [])[:3],
        "csv_author": csv_author,
        "pub_year": year if isinstance(year, int) and -3000 <= year <= 2100 else None,
        "page_count": pages if pages and pages > 0 else None,
        "isbn": ol.pick_isbn(edition.get("isbn_13")),
        "cover_url": f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg" if doc.get("cover_i") else None,
        "avg_rating": round(min(max(doc.get("ratings_average") or 0, 0), 5), 2),
        "ratings_count": doc.get("ratings_count") or 0,
        "publisher": publisher,
        "description": ol.clean_text(work.get("description")),
    }


def fetch():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if TEMPLATE in (r.get("Book:description") or "")]
    print(f"{len(rows)} placeholder books in the CSV", flush=True)
    out, missing = [], []
    with ThreadPoolExecutor(max_workers=int(os.getenv('FIX_WORKERS', '6'))) as pool:
        for i, (title, fix) in enumerate(pool.map(lookup, rows), 1):
            if fix:
                out.append(fix)
            else:
                missing.append(title)
            if i % 10 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    with open(FIX_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(out)} books to {FIX_PATH}. Not found: {missing or 'none'}")


# ---------------------------------------------------------------------
# Merge: pinned facts (author, year) + Open Library (everything else)
# ---------------------------------------------------------------------
MIN_RATINGS = 5  # fewer Open Library ratings than this says nothing (e.g. 5.0 from 1 rating)


def records():
    """One clean record per curated title, built from FACTS and curated_books_fix.json."""
    fixes = {}
    if os.path.exists(FIX_PATH):
        with open(FIX_PATH, encoding="utf-8") as f:
            fixes = {x["title"]: x for x in json.load(f)}
    out = {}
    for title, (authors, year) in FACTS.items():
        ol_data = fixes.get(title) if title not in WRONG_MATCH else None
        ol_data = ol_data or {}
        rated = (ol_data.get("ratings_count") or 0) >= MIN_RATINGS
        by = " and ".join(authors)
        out[title] = {
            "title": title,
            "authors": authors,
            "pub_year": year,
            "description": ol_data.get("description")
                           or f"{title} by {by}" + (f", first published in {year}." if year else "."),
            "cover_url": ol_data.get("cover_url"),
            "page_count": ol_data.get("page_count"),
            "isbn": ol_data.get("isbn"),
            "publisher": ol_data.get("publisher"),
            "avg_rating": ol_data["avg_rating"] if rated else 0,
            "ratings_count": ol_data["ratings_count"] if rated else 0,
        }
    return out


# ---------------------------------------------------------------------
# apply: merged records -> database
# ---------------------------------------------------------------------
def apply(database_url=None):
    url = database_url or os.getenv("DATABASE_ADMIN_URL") or os.getenv("DATABASE_URL")
    conn = psycopg2.connect(url)
    fixed = 0
    with conn, conn.cursor() as cur:
        cur.execute("SELECT isbn FROM book WHERE isbn IS NOT NULL")
        taken_isbns = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT author_id, name FROM author ORDER BY author_id DESC")
        authors_by_key = {ol.norm_key(name): aid for aid, name in cur.fetchall()}  # lowest id wins

        for rec in records().values():
            cur.execute("SELECT book_id FROM book WHERE title = %s AND description LIKE %s",
                        (rec["title"], f"%{TEMPLATE}%"))
            row = cur.fetchone()
            if not row:
                continue  # already fixed, or not in this database
            book_id = row[0]

            publisher_id = None
            if rec["publisher"]:
                cur.execute("""INSERT INTO publisher (name) VALUES (%s)
                               ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING publisher_id""",
                            (rec["publisher"],))
                publisher_id = cur.fetchone()[0]

            isbn = rec["isbn"] if rec["isbn"] and rec["isbn"] not in taken_isbns else None
            if isbn:
                taken_isbns.add(isbn)

            # Ratings: Open Library's numbers plus any ratings readers already gave here
            cur.execute("SELECT count(rating), COALESCE(sum(rating), 0) FROM diary_entry "
                        "WHERE book_id = %s AND rating IS NOT NULL", (book_id,))
            local_n, local_sum = cur.fetchone()
            n = rec["ratings_count"] + local_n
            avg = round((rec["avg_rating"] * rec["ratings_count"] + float(local_sum)) / n, 2) if n else 0

            # The fake ISBN cover URL shows nothing, so clear it when there is no real one
            cur.execute(
                """
                UPDATE book SET description = %s, pub_year = %s, page_count = %s, isbn = %s,
                       cover_url = %s, avg_rating = %s, ratings_count = %s, publisher_id = %s
                WHERE book_id = %s
                """,
                (rec["description"], rec["pub_year"], rec["page_count"], isbn, rec["cover_url"],
                 avg, n, publisher_id, book_id),
            )

            # Authors: replace the links, reusing an existing author row ("H. G. Wells" = "H.G. Wells")
            cur.execute("DELETE FROM book_author WHERE book_id = %s", (book_id,))
            for name in rec["authors"]:
                author_id = authors_by_key.get(ol.norm_key(name))
                if not author_id:
                    cur.execute("INSERT INTO author (name) VALUES (%s) RETURNING author_id", (name,))
                    author_id = authors_by_key[ol.norm_key(name)] = cur.fetchone()[0]
                cur.execute("INSERT INTO book_author VALUES (%s, %s) ON CONFLICT DO NOTHING", (author_id, book_id))
            fixed += 1

        # Authors that only had placeholder books and now have none
        cur.execute("""DELETE FROM author a WHERE NOT EXISTS (SELECT 1 FROM book_author ba WHERE ba.author_id = a.author_id)
                       AND NOT EXISTS (SELECT 1 FROM author_follow af WHERE af.author_id = a.author_id)
                       AND a.bio IS NULL AND a.photo_url IS NULL""")
        orphans = cur.rowcount
    conn.close()
    print(f"Fixed {fixed} curated books (removed {orphans} authors left with no books).")


# ---------------------------------------------------------------------
# csv: merged records -> master_curated_books_universe_180.csv
# ---------------------------------------------------------------------
def rewrite_csv():
    recs = records()
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    changed = 0
    for r in rows:
        rec = recs.get(r["Book:title"].strip())
        if not rec or TEMPLATE not in (r.get("Book:description") or ""):
            continue
        r.update({
            "Book:description": rec["description"],
            "Book:thumbnail": rec["cover_url"] or "",
            "Book:published_year": rec["pub_year"] if rec["pub_year"] is not None else "",
            "Book:average_rating": rec["avg_rating"],
            "Book:num_pages": rec["page_count"] or "",
            "Book:ratings_count": rec["ratings_count"],
            "Book:isbn13": rec["isbn"] or "",
            "Book:isbn10": "",
            "Author:name": ", ".join(rec["authors"]),
        })
        changed += 1
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    print(f"Rewrote {changed} rows in {os.path.basename(CSV_PATH)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        fetch()
    elif cmd == "apply":
        apply(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "csv":
        rewrite_csv()
    else:
        print(__doc__)
