from . import utils

# TODO: Override with port=NNNN if specified by environment

@utils.cmdline
def renderer(*, gain:"g"=0.0):
	"""Invoke the infinite renderer

	gain: dB gain (positive or negative) for volume adjustment
	"""
	from . import renderer
	renderer.run(gain=gain) # doesn't return

@utils.cmdline
def major_glitch(*, dev=False):
	"""Rebuild the Major Glitch"""
	utils.enable_timer()
	from . import renderer
	renderer.major_glitch(profile=dev)

@utils.cmdline
def audition(id1, id2, fn):
	"""Audition a transition

	id1: ID of earlier track (will render last 10s)

	id2: ID of later track (will render first 10s)

	fn: File name to save into
	"""
	from . import renderer
	renderer.audition(id1, id2, fn)

@utils.cmdline
def main(*, dev=False):
	"""Start the main server (debug mode - production uses gunicorn)"""
	from . import server
	server.run(disable_logins=dev) # doesn't return

utils.main()
