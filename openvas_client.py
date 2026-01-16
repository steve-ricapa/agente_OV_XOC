from gvm.connections import TLSConnection

try:
    from gvm.protocols.gmp import Gmp as _GmpClass  # type: ignore
except Exception:
    _GmpClass = None

try:
    from gvm.protocols.gmp import GMP as _GMPClass  # type: ignore
except Exception:
    _GMPClass = None


def _pick_gmp_class():
    if _GmpClass is not None:
        return _GmpClass
    if _GMPClass is not None:
        return _GMPClass
    raise ImportError("No se pudo importar Gmp/GMP desde gvm.protocols.gmp (python-gvm no compatible o no instalado).")


class OpenVASClient:
    def __init__(self, host: str, port: int, username: str, password: str, tls_verify: bool = True):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.tls_verify = bool(tls_verify)

        self.connection = None
        self.gmp = None

    def __enter__(self):
        self.connection = TLSConnection(hostname=self.host, port=self.port)

        GmpProto = _pick_gmp_class()
        self.gmp = GmpProto(connection=self.connection)

        if hasattr(self.gmp, "authenticate"):
            self.gmp.authenticate(self.username, self.password)  # type: ignore
        elif hasattr(self.gmp, "login"):
            self.gmp.login(self.username, self.password)  # type: ignore
        else:
            raise AttributeError(
                f"El objeto {type(self.gmp).__name__} no tiene authenticate() ni login(). "
                "Probable incompatibilidad de versión python-gvm vs gvmd/GMP."
            )

        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.gmp and hasattr(self.gmp, "disconnect"):
                self.gmp.disconnect()  # type: ignore
        except Exception:
            pass

    def get_tasks(self) -> str:
        return self.gmp.get_tasks()  # type: ignore

    def get_report(self, report_id: str) -> str:
        return self.gmp.get_report(report_id=report_id, details=True)  # type: ignore
