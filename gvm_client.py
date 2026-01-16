from __future__ import annotations
from typing import Optional

class GVMClient:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password

        self._err: Optional[Exception] = None
        self._TLSConnection = None
        self._GMP = None

        self.connection = None
        self._gmp_cm = None
        self.gmp = None

        try:
            from gvm.connections import TLSConnection  # type: ignore
            from gvm.protocols.gmp import GMP  # type: ignore
            self._TLSConnection = TLSConnection
            self._GMP = GMP
        except Exception as e:
            self._err = e

    def __enter__(self):
        if self._TLSConnection is None or self._GMP is None:
            raise ModuleNotFoundError(
                "No está disponible el módulo 'gvm' (instala python-gvm en ESTE venv). "
                f"Detalle: {type(self._err).__name__}: {self._err}"
            )

        # TLSConnection(hostname=..., port=..., timeout=...)  :contentReference[oaicite:3]{index=3}
        try:
            self.connection = self._TLSConnection(hostname=self.host, port=self.port, timeout=30)  # type: ignore
        except TypeError:
            self.connection = self._TLSConnection(hostname=self.host, port=self.port)  # type: ignore

        self._gmp_cm = self._GMP(connection=self.connection)  # type: ignore
        self.gmp = self._gmp_cm.__enter__()  # GMP real (selecciona versión)

        # authenticate según la guía de uso :contentReference[oaicite:4]{index=4}
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
