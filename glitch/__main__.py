from . import config
from . import apikeys
import os
import socket
import argparse

# Hack: Allow "python -m glitch database" to be the same as "glitch.database"
import sys
if len(sys.argv) > 1 and sys.argv[1] == "database":
	from . import database
	import clize
	sys.exit(clize.run(*database.commands, args=sys.argv[1:]))

import logging
parser = argparse.ArgumentParser(description="Invoke the Infinite Glitch server(s)")
parser.add_argument("server", help="Server to invoke", choices=["main", "renderer", "major_glitch"], nargs="?", default="main")
parser.add_argument("-l", "--log", help="Logging level", type=lambda x: x.upper(),
	choices=logging._nameToLevel, # NAUGHTY
	default="INFO")
parser.add_argument("--dev", help="Dev mode (no logins)", action='store_true')
arguments = parser.parse_args()
log = logging.getLogger(__name__)
logging.basicConfig(level=getattr(logging, arguments.log), format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')

# Look for a socket provided by systemd
sock = None
try:
	pid = int(os.environ.get("LISTEN_PID", ""))
	fd_count = int(os.environ.get("LISTEN_FDS", ""))
except ValueError:
	pid = fd_count = 0
if pid == os.getpid() and fd_count >= 1:
	# The PID matches - we've been given at least one socket.
	# The sd_listen_fds docs say that they should start at FD 3.
	sock = socket.socket(fileno=3)
	print("Got %d socket(s)" % fd_count, file=sys.stderr)

# TODO: Override with port=NNNN if specified by environment
if arguments.server == "renderer":
	from . import renderer
	renderer.run(sock=sock) # doesn't return
elif arguments.server == "major_glitch":
	from . import utils; utils.enable_timer()
	from . import renderer
	renderer.major_glitch(profile=arguments.dev)
	logging.info("Major Glitch built successfully.")
else:
	from . import server
	server.run(disable_logins=arguments.dev) # doesn't return
