"""
Gives an account the admin (or moderator / reader) role.

    backend\\venv\\Scripts\\python.exe backend\\scripts\\make_admin.py your_username
    backend\\venv\\Scripts\\python.exe backend\\scripts\\make_admin.py some_user moderator

Sign in on the website once first, so the account exists. Then reload the site:
the Admin page appears in the menu.
"""
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

ROLES = ("admin", "moderator", "reader")


def main():
    if len(sys.argv) < 2 or (len(sys.argv) > 2 and sys.argv[2] not in ROLES):
        sys.exit("usage: make_admin.py <username> [admin|moderator|reader]")
    username, role = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "admin")
    with psycopg2.connect(os.getenv("DATABASE_URL")) as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET role = %s WHERE username = %s RETURNING user_id", (role, username))
        if cur.fetchone():
            print(f"{username} is now {role}. Reload the website.")
            return
        cur.execute("SELECT username FROM users ORDER BY created_at DESC LIMIT 10")
        names = ", ".join(r[0] for r in cur.fetchall()) or "none yet (sign in on the website first)"
        sys.exit(f"No user called {username}. Recent usernames: {names}")


if __name__ == "__main__":
    main()
