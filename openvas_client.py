from gvm.connections import TLSConnection
from gvm.protocols.gmp import Gmp

class OpenVASClient:

    def __init__(self, host, port, username, password, tls_verify):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.tls_verify = tls_verify

    def __enter__(self):
        self.connection = TLSConnection(
            host=self.host,
            port=self.port,
            verify=self.tls_verify
        )
        self.gmp = Gmp(connection=self.connection)
        self.gmp.authenticate(self.username, self.password)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.gmp.disconnect()
        except:
            pass

    def get_tasks(self):
        return self.gmp.get_tasks()

    def get_report(self, report_id):
        return self.gmp.get_report(report_id=report_id, details=True)
