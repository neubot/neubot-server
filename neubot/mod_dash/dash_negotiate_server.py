# mod_dash/server_negotiate.py

#
# Copyright (c) 2011-2013
#     Nexa Center for Internet & Society, Politecnico di Torino (DAUIN)
#     and Simone Basso <bassosimone@gmail.com>
#
# This file is part of Neubot <http://www.neubot.org/>.
#
# Neubot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Neubot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Neubot.  If not, see <http://www.gnu.org/licenses/>.
#

""" MPEG DASH negotiate server """

# Adapted from neubot/negotiate/server_raw.py

import base64
import logging
import hashlib

from ..negotiate_server_module import NegotiateServerModule

from ..runtime import utils
from .. import backend

from .server_glue import save_web100_snap

class DASHNegotiateServer(NegotiateServerModule):
    """ Negotiator for MPEG DASH test """

    def __init__(self):
        NegotiateServerModule.__init__(self)
        self.peers = {}

    @staticmethod
    def _stream_to_sha256(stream):
        """ Stream to SHA256 identifier """
        sha256 = hashlib.new("sha256")
        sha256.update(str(hash(stream)))
        return base64.b64encode(sha256.digest())

    def unchoke(self, stream, request_body):
        """ Invoked when we must unchoke a session """

        sha256 = self._stream_to_sha256(stream)

        if sha256 in self.peers:
            raise RuntimeError("dash: multiple unchokes: %s", sha256)

        self.peers[sha256] = {
            "iteration": 0,
            "web100_dirname": "",
            "data": [],
        }
        stream.atclose(self._update_peers)

        logging.debug("dash: add sha256: %s", sha256)

        return {
                "authorization": sha256,
                "port": 8080, # XXX is this used?

                # For now just accept the proposal from the client
                "dash_rates": request_body["dash_rates"],
               }

    def collect(self, stream, request_body):
        """ Invoked when we must save the result of a session """

        sha256 = self._stream_to_sha256(stream)

        if sha256 not in self.peers:
            raise RuntimeError("dash: not authorized: %s", sha256)

        # Note: no more than one collect per session
        result = self.peers.pop(sha256)

        save_web100_snap(result)

        logging.debug("dash: del sha256 (OK): %s", sha256)

        server_timestamp = utils.timestamp()

        backend.store("dash", {
                      "srvr_schema_version": 3,
                      "srvr_timestamp": server_timestamp,
                      "client": request_body,
                      "server": result["data"],
                     })

        return result["data"]

    def _update_peers(self, stream, ignored):
        """ Invoked when a session has been closed """

        sha256 = self._stream_to_sha256(stream)

        # Note: if collect is successful self.peers[sha256] doesn't exist
        if sha256 in self.peers:
            logging.warning("dash: del sha256 (ERR): %s", sha256)
            del self.peers[sha256]
