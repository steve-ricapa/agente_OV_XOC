from __future__ import annotations
from typing import Optional

class GVMClient:
    def __init__(self, host: str, port: int, user: str, password: str, socket_path: str = ""):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.socket_path = (socket_path or "").strip()

        self._err: Optional[Exception] = None
        self._TLSConnection = None
        self._UnixSocketConnection = None
        self._GMP = None

        self.connection = None
        self._gmp_cm = None
        self.gmp = None

        try:
            from gvm.connections import TLSConnection, UnixSocketConnection  # type: ignore
            from gvm.protocols.gmp import GMP  # type: ignore
            self._TLSConnection = TLSConnection
            self._UnixSocketConnection = UnixSocketConnection
            self._GMP = GMP
        except Exception as e:
            self._err = e

    def __enter__(self):
        if self._GMP is None or (self._TLSConnection is None and self._UnixSocketConnection is None):
            raise ModuleNotFoundError(
                "python-gvm no está disponible en este entorno. "
                f"Detalle: {type(self._err).__name__}: {self._err}"
            )

        # ✅ Si hay socket, úsalo (recomendado)
        if self.socket_path:
            self.connection = self._UnixSocketConnection(path=self.socket_path)  # type: ignore
        else:
            self.connection = self._TLSConnection(hostname=self.host, port=self.port)  # type: ignore

        self._gmp_cm = self._GMP(connection=self.connection)  # type: ignore
        self.gmp = self._gmp_cm.__enter__()
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
