"""python -m app.hash_password  ->  prints the value for APP_PASSWORD_HASH."""
import getpass

import bcrypt

pw = getpass.getpass("New password: ")
if pw != getpass.getpass("Repeat: "):
    raise SystemExit("Passwords differ")
print(bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
