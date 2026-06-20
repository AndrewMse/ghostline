from __future__ import annotations

import argparse
import logging
import shutil
import sys

from .db import Database
from .models import TrackInfo
from .recorder import Recorder
from .service import Coach
from .sources import LiftoffSource, SyntheticSource, VelocidroneSource
from .sources.liftoff import config_json, config_path
from .synthetic import FigureEight, fly


def serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .main import create_app

    source = {
        "demo": lambda: SyntheticSource(speed=args.demo_speed),
        "liftoff": lambda: LiftoffSource(args.liftoff_host, args.liftoff_port),
        "velocidrone": lambda: VelocidroneSource(args.vd_host, args.vd_port, args.vd_pilot),
        "none": lambda: None,
    }[args.source]()
    app = create_app(args.db, source)
    print(f"Ghostline on http://{args.host}:{args.port}  (source: {args.source}, db: {args.db})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def seed_demo(args: argparse.Namespace) -> None:
    """Record a few sessions of the synthetic pilot through the real recorder."""
    db = Database(args.db)
    recorder = Recorder(db, Coach(db), "demo")
    track = FigureEight()
    for k in range(args.sessions):
        recorder.handle(TrackInfo(track.name))
        # A pilot who gets a little faster and more consistent every session.
        skill = 0.94 + 0.03 * k
        for sample in fly(track, args.laps, seed=100 + k, skill=skill, mistake_rate=max(0.3 - 0.1 * k, 0.1)):
            recorder.handle(sample)
        recorder.close_session()
    for s in db.sessions()[: args.sessions]:
        best = f"{s['best']:.3f}s" if s["best"] else "-"
        print(f"session {s['id']}: {s['laps']} laps, best {best}")


def liftoff_config(args: argparse.Namespace) -> None:
    text = config_json(args.host, args.port)
    path = config_path()
    if not args.write:
        print(f"# Save as {path}\n{text}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy(path, path.with_suffix(".json.bak"))
        print(f"backed up the existing file to {path.with_suffix('.json.bak')}")
    path.write_text(text)
    print(f"wrote {path}; reset the drone in Liftoff to load it")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="ghostline", description="FPV race coach for Velocidrone and Liftoff")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="record telemetry and serve the web app")
    s.add_argument("--source", choices=["velocidrone", "liftoff", "demo", "none"], default="demo")
    s.add_argument("--db", default="ghostline.db")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--vd-host", help="Velocidrone PC's LAN IP (default: this machine's)")
    s.add_argument("--vd-port", type=int, default=60003)
    s.add_argument("--vd-pilot", help="your Velocidrone name, needed in multiplayer")
    s.add_argument("--liftoff-host", default="127.0.0.1")
    s.add_argument("--liftoff-port", type=int, default=9001)
    s.add_argument("--demo-speed", type=float, default=1.0, help="demo playback speed")
    s.set_defaults(func=serve)

    d = sub.add_parser("seed-demo", help="fill the database with synthetic sessions")
    d.add_argument("--db", default="ghostline.db")
    d.add_argument("--sessions", type=int, default=3)
    d.add_argument("--laps", type=int, default=10)
    d.set_defaults(func=seed_demo)

    lc = sub.add_parser("liftoff-config", help="print or write Liftoff's TelemetryConfiguration.json")
    lc.add_argument("--host", default="127.0.0.1")
    lc.add_argument("--port", type=int, default=9001)
    lc.add_argument("--write", action="store_true", help="write it (backs up an existing file)")
    lc.set_defaults(func=liftoff_config)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
