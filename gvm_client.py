from gvm.connections import TLSConnection
from gvm.protocols.gmp import GMP


class GVMClient:
    def __init__(self, host: str, port: int, user: str, password: str, tls_verify: bool = True):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.tls_verify = bool(tls_verify)

        self.connection = None

        # GMP debe manejarse como context manager
        self._gmp_cm = None
        self.gmp = None

    def __enter__(self):
        # python-gvm usa hostname=
        self.connection = TLSConnection(hostname=self.host, port=self.port)

        # Creamos el context manager
        self._gmp_cm = GMP(connection=self.connection)

        # Entramos manualmente para obtener la instancia real (GMPvXXX)
        self.gmp = self._gmp_cm.__enter__()

        # Ahora sí existe authenticate()
        self.gmp.authenticate(self.user, self.password)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._gmp_cm is not None:
                self._gmp_cm.__exit__(exc_type, exc, tb)
        except Exception:
            pass

    def get_tasks(self) -> str:
        return self.gmp.get_tasks()  # type: ignore

    def get_report(self, report_id: str) -> str:
        return self.gmp.get_report(report_id=report_id, details=True)  # type: ignore
