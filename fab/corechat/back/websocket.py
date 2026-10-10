# corechat's broadcaster: the agent pages' bus. see fab/websocket.py for the machinery.

from fab.websocket import Broadcaster

_bus = Broadcaster()

clients = _bus.clients            # user -> that user's open corechat sockets
broadcast = _bus.send
start_broadcaster = _bus.start
