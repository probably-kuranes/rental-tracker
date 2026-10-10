"""Command line: python -m tracker.cli <command>

  ingest PATH        load every PDF under a folder (backfill)
  mail [--since D]   read Mid South's emails from the Gmail account (daily cron)
  serve              run the web app (PORT, default 8000)
  check              list documents that did not reconcile
"""
from __future__ import annotations

import argparse
import logging
import os

from sqlalchemy import select


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    p = argparse.ArgumentParser(prog='tracker')
    sub = p.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('ingest'); i.add_argument('path')
    m = sub.add_parser('mail'); m.add_argument('--since', default=None)
    sub.add_parser('serve')
    sub.add_parser('check')
    args = p.parse_args(argv)

    if args.cmd == 'ingest':
        from .ingest import ingest_folder
        print(dict(ingest_folder(args.path)))
    elif args.cmd == 'mail':
        from . import mailbox
        print(mailbox.run(args.since) if args.since else mailbox.run())
    elif args.cmd == 'serve':
        import uvicorn
        uvicorn.run('tracker.app:app', host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
    elif args.cmd == 'check':
        from . import db
        with db.session() as s:
            for d in s.scalars(select(db.Document).where(db.Document.status.notin_(['parsed', 'duplicate', 'empty']))):
                print(f"{d.id:>4} {d.status:<13} {d.filename}\n       {d.problems or ''}")


if __name__ == '__main__':
    main()
