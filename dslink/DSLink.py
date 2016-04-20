import base64
import hashlib
import logging
from urlparse import urlparse
import signal
import sys
from twisted.internet import reactor

from dslink.Crypto import Keypair
from dslink.Handshake import Handshake
from dslink.Requester import Requester
from dslink.Responder import Responder
from dslink.WebSocket import WebSocket


class DSLink:
    """
    Base DSLink class which creates the node structure,
    subscription/stream manager, and connects to the broker.
    """

    def __init__(self, config):
        """
        Construct for DSLink.
        :param config: Configuration object.
        """
        self.active = False
        self.needs_auth = False

        # DSLink Configuration
        self.config = config
        self.server_config = None

        # Logger setup
        self.logger = self.create_logger("DSLink", self.config.log_level)
        self.logger.info("Starting DSLink")

        # Signal setup
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        # Requester and Responder setup
        if self.config.requester:
            self.requester = Requester(self)
        if self.config.responder:
            self.responder = Responder(self)
            self.responder.start()

        # DSLink setup
        self.keypair = Keypair(self.config.keypair_path)
        self.handshake = Handshake(self, self.keypair)
        self.handshake.run_handshake()
        self.dsid = self.handshake.get_dsid()

        # Connection setup
        self.wsp = None
        self.websocket = WebSocket(self)

        self.call_later(1, self.start)

        self.logger.info("Started DSLink")
        self.logger.debug("Starting reactor")
        reactor.run(installSignalHandlers=False)

    def start(self):
        """
        Called once the DSLink is initialized and connected.
        Override this rather than the constructor.
        """
        pass

    def stop(*args):
        """
        Called when the DSLink is going to stop.
        Override this if you start any threads you need to stop.
        Be sure to call the super function.
        :param args: Signal arguments.
        :return:
        """
        reactor.removeAll()
        reactor.iterate()
        reactor.stop()
        try:
            sys.exit(0)
        except SystemExit:
            pass

    # noinspection PyMethodMayBeStatic
    def get_default_nodes(self, super_root):
        """
        Create the default Node structure in this, override it.
        :param super_root: Super Root.
        :return: Super Root with default Node structure.
        """
        return super_root

    def get_auth(self):
        """
        Get auth parameter for connection.
        :return: Auth parameter.
        """
        auth = str(self.server_config["salt"]) + self.shared_secret
        auth = base64.urlsafe_b64encode(hashlib.sha256(auth).digest()).decode("utf-8").replace("=", "")
        return auth

    def get_url(self):
        """
        Get full WebSocket URL.
        :return: WebSocket URL.
        """
        websocket_uri = self.config.broker[:-5].replace("http", "ws") + "/ws?dsId=%s" % self.dsid
        if self.needs_auth:
            websocket_uri += "&auth=%s" % self.get_auth()
        token = self.config.token_hash(self.dsid, self.config.token)
        if token is not None:
            websocket_uri += token
        url = urlparse(websocket_uri)
        if url.port is None:
            port = 80
        else:
            port = url.port
        return websocket_uri, url, port

    @staticmethod
    def create_logger(name, log_level=logging.INFO):
        """
        Create a logger with the specified name.
        :param name: Logger name.
        :param log_level: Output Logger level.
        :return: Logger instance.
        """
        # Logger setup
        formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s')
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        ch.setLevel(log_level)
        logger = logging.getLogger(name)
        logger.setLevel(log_level)
        logger.addHandler(ch)
        return logger

    @staticmethod
    def add_padding(string):
        """
        Add padding to a URL safe base64 string.
        :param string:
        :return:
        """
        while len(string) % 4 != 0:
            string += "="
        return string

    @staticmethod
    def call_later(delay, call, *args, **kw):
        """
        Call function later.
        :param delay: Seconds to delay.
        :param call: Method to call.
        :param args: Arguments.
        :return: DelayedCall instance.
        """
        return reactor.callLater(delay, call, *args, **kw)

