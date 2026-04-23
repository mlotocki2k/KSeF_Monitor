"""
CLI for UI user account administration.

Usage:
    python -m app.user_admin list
    python -m app.user_admin add <username>
    python -m app.user_admin reset-password <username>
    python -m app.user_admin delete <username>
    python -m app.user_admin cleanup-sessions

Reads DB path from CONFIG_PATH env var (default: ./config.json).
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from app.database import Database
from app.ui_auth import (
    cleanup_expired_sessions,
    count_users,
    create_user,
    get_user_by_username,
    set_password,
    validate_password,
    validate_username,
)


def _open_db() -> Database:
    config_path = Path(os.environ.get("CONFIG_PATH", "config.json"))
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(2)
    cfg = json.loads(config_path.read_text())
    db_path = cfg.get("database", {}).get("path", "data/ksef_monitor.db")
    return Database(db_path)


def _prompt_password(prompt: str = "Hasło: ") -> str:
    p1 = getpass.getpass(prompt)
    p2 = getpass.getpass("Powtórz hasło: ")
    if p1 != p2:
        print("Hasła nie zgadzają się.", file=sys.stderr)
        sys.exit(1)
    err = validate_password(p1)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)
    return p1


def cmd_list(args):
    db = _open_db()
    with db.get_session() as s:
        from sqlalchemy import select

        from app.database import UiUser

        rows = s.execute(select(UiUser).order_by(UiUser.id)).scalars().all()
        if not rows:
            print("Brak użytkowników.")
            return
        print(f"{'ID':<5}{'USERNAME':<32}{'CREATED':<22}{'LAST LOGIN':<22}")
        for u in rows:
            created = u.created_at.strftime("%Y-%m-%d %H:%M") if u.created_at else "—"
            last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "—"
            print(f"{u.id:<5}{u.username:<32}{created:<22}{last:<22}")


def cmd_add(args):
    err = validate_username(args.username)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)
    db = _open_db()
    with db.get_session() as s:
        if get_user_by_username(s, args.username):
            print(f"Użytkownik {args.username!r} już istnieje.", file=sys.stderr)
            sys.exit(1)
        password = _prompt_password()
        u = create_user(s, args.username, password)
    print(f"Utworzono użytkownika {u.username!r} (id={u.id}).")


def cmd_reset_password(args):
    db = _open_db()
    with db.get_session() as s:
        u = get_user_by_username(s, args.username)
        if not u:
            print(f"Brak użytkownika {args.username!r}.", file=sys.stderr)
            sys.exit(1)
        password = _prompt_password("Nowe hasło: ")
        set_password(s, u, password)
    print(f"Hasło zmienione dla {args.username!r}. Wszystkie sesje unieważnione.")


def cmd_delete(args):
    db = _open_db()
    with db.get_session() as s:
        u = get_user_by_username(s, args.username)
        if not u:
            print(f"Brak użytkownika {args.username!r}.", file=sys.stderr)
            sys.exit(1)
        if count_users(s) == 1:
            print("Nie można usunąć ostatniego użytkownika (wymagałby setup wizard).", file=sys.stderr)
            sys.exit(1)
        s.delete(u)
        s.commit()
    print(f"Usunięto użytkownika {args.username!r}.")


def cmd_cleanup_sessions(args):
    db = _open_db()
    with db.get_session() as s:
        n = cleanup_expired_sessions(s)
    print(f"Usunięto {n} wygasłych sesji.")


def main():
    p = argparse.ArgumentParser(prog="user_admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Lista użytkowników").set_defaults(func=cmd_list)

    pa = sub.add_parser("add", help="Dodaj użytkownika")
    pa.add_argument("username")
    pa.set_defaults(func=cmd_add)

    pr = sub.add_parser("reset-password", help="Zresetuj hasło użytkownika")
    pr.add_argument("username")
    pr.set_defaults(func=cmd_reset_password)

    pd = sub.add_parser("delete", help="Usuń użytkownika")
    pd.add_argument("username")
    pd.set_defaults(func=cmd_delete)

    sub.add_parser("cleanup-sessions", help="Usuń wygasłe sesje").set_defaults(
        func=cmd_cleanup_sessions
    )

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
