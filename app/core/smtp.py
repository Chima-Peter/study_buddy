from email.message import EmailMessage
from logging import Logger
from queue import Empty, Queue
import ssl
import smtplib


class SMTPPool:
    def __init__(
        self,
        max_connections: int,
        timeout: int,
        host: str,
        port: int,
        username: str,
        password: str,
        logger: Logger
    ):
        self.max_connections = max_connections
        self.timeout = timeout
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.logger = logger
        self.context = ssl.create_default_context()
        self.pool = Queue[smtplib.SMTP_SSL](maxsize=self.max_connections)

        for _ in range(self.max_connections):
            self.pool.put(self._create_connection())

        self.logger.info(f"SMTP pool created with {self.max_connections} connections")

    def send_email(self, email: EmailMessage):
        connection = None
        try:
            connection = self._acquire()
            connection.send_message(email)
        except Empty:
            self.logger.error("SMTP pool is empty")
            raise
        except Exception as e:
            self.logger.error(f"Error sending email: {e}")
            if connection is not None:
                self._discard_connection(connection)
                try:
                    connection = self._create_connection()
                except Exception:
                    connection = None
                    raise
            raise
        finally:
            if connection is not None:
                self.pool.put(connection)

    def close(self):
        while not self.pool.empty():
            connection = self.pool.get()

            try:
                connection.quit()
            except Exception as e:
                self.logger.error(f"Error closing connection: {e}")

        self.logger.info("SMTP pool closed")

    def _create_connection(self):
        connection = smtplib.SMTP_SSL(
            host=self.host,
            port=self.port,
            context=self.context,
        )
        connection.login(self.username, self.password)
        return connection

    def _is_healthy(self, connection: smtplib.SMTP_SSL) -> bool:
        try:
            return connection.noop()[0] == 250
        except Exception:
            return False

    def _discard_connection(self, connection: smtplib.SMTP_SSL):
        try:
            connection.quit()
        except smtplib.SMTPException:
            try:
                connection.close()
            except Exception:
                pass

    def _acquire(self) -> smtplib.SMTP_SSL:
        connection = self.pool.get(timeout=self.timeout)
        if not self._is_healthy(connection):
            self._discard_connection(connection)
            connection = self._create_connection()
        return connection
