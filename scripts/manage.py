"""Create/promote an administrator or reset a password in the selected database."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import create_user, hash_password  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.main import Credentials  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["create-admin", "reset-password"])
parser.add_argument("email")
args = parser.parse_args()
password = getpass.getpass("New password (10–128 characters): ")
if password != getpass.getpass("Confirm password: ") or not 10 <= len(password) <= 128:
    parser.error("Passwords must match and contain 10–128 characters.")
email = Credentials(email=args.email, password=password).email
db = Database(Settings().data_dir / "cloudlab.db")
user = db.one("SELECT * FROM users WHERE email=?", (email,))
if user:
    db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), user["id"]))
    db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    if args.action == "create-admin":
        db.execute("UPDATE users SET role='admin' WHERE id=?", (user["id"],))
elif args.action == "create-admin":
    create_user(db, "Administrator", email, password, "admin")
else:
    parser.error("No account with that email exists.")
print("Account updated. Sign in with the new password.")
