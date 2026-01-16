# AGENTE OPENVAS – LABORATORIO

Agente ligero escrito en Python que simula la recolección de reportes de vulnerabilidades y los envía a un backend.  
Diseñado para **entornos de laboratorio** y pruebas.

---

## 1. Descripción

Este proyecto implementa un **agente recolector** que:

1. Lee configuraciones desde `.env`
2. Obtiene reportes (simulados o reales)
3. Procesa severidades
4. Evita duplicados usando `state.json`
5. Envía los resultados a un backend REST
6. Se ejecuta en bucle cada X segundos

Arquitectura:

```
[Agente Python] ---> [Backend API]
```

No realiza escaneos.  
Solo **consume reportes existentes**.

---

## 2. Requisitos

### Software

- Python 3.9 o superior
- Windows / Linux / macOS
- Acceso a internet (si usa backend remoto)

### Librerías

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Contenido:

- requests
- python-dotenv

---

## 3. Estructura del proyecto

```
agente_OV_XOC/
│
├── main.py            # Punto de entrada
├── config.py          # Carga de variables .env
├── services.py        # Lógica de negocio
├── openvas_client.py  # Cliente OpenVAS (si se usa)
├── gvm_client.py      # Cliente GMP
├── requirements.txt   # Dependencias
├── .env               # Configuración
├── state.json         # Control de duplicados
├── tests/             # Pruebas unitarias
└── README.md
```

---

## 4. Archivo .env

Variables usadas por el agente:

### Backend

```
TXDXAI_INGEST_URL
TXDXAI_COMPANY_ID
TXDXAI_API_KEY
```

| Variable | Descripción |
|------------|-------------|
| TXDXAI_INGEST_URL | Endpoint del backend |
| TXDXAI_COMPANY_ID | ID de empresa |
| TXDXAI_API_KEY | Token de autenticación |

---

### Configuración del agente

```
COLLECTOR
POLL_SECONDS
STATE_PATH
META_MAX_KB
```

| Variable | Función |
|------------|---------|
| COLLECTOR | Tipo de fuente |
| POLL_SECONDS | Intervalo de consulta |
| STATE_PATH | Archivo de estado |
| META_MAX_KB | Tamaño máximo payload |

---

### OpenVAS (si se usa)

```
GVM_HOST
GVM_PORT
GVM_USERNAME
GVM_PASSWORD
GVM_TLS_VERIFY
```

Definen conexión al scanner.

---

## 5. Funcionamiento interno

### Flujo

1. Carga `.env`
2. Lee `state.json`
3. Entra en loop
4. Consulta reportes
5. Verifica duplicados
6. Procesa XML
7. Envía al backend
8. Guarda estado
9. Espera X segundos
10. Repite

---

## 6. Ejecución

### Iniciar agente

```bash
python main.py
```

Debe mostrar:

```
=== AGENTE GMP ===
Nuevo ciclo
```

---

## 7. state.json

Archivo que evita enviar el mismo reporte dos veces.

Ejemplo:

```json
{
  "sent": [
    "report_id_1",
    "report_id_2"
  ]
}
```

---

## 8. Manejo de errores

El agente maneja:

- Timeout backend
- Errores HTTP
- Conexión fallida
- XML inválido
- Variables faltantes

No se detiene ante errores, continúa ejecución.

---

## 9. Rendimiento

Características:

- Bajo consumo de CPU
- Sin threads
- Sin procesos paralelos
- Polling controlado
- Ejecución estable

El caché Python fue desactivado para laboratorio (`__pycache__`).

---

## 10. Seguridad (laboratorio)

- Credenciales en `.env`
- TLS opcional
- API keys en texto plano

**Solo para laboratorio.**  
No usar en producción.

---

## 11. Pruebas

Ejecutar:

```bash
pytest
```

Incluye tests básicos para:

- Procesamiento XML
- Mapeo de severidades

---

## 12. Problemas comunes

### Error: ModuleNotFound

Ejecutar desde la carpeta correcta:

```bash
cd agente_OV_XOC
python main.py
```

---

### No se conecta al backend

Verificar:

- URL correcta
- Firewall
- Backend activo

---

## 13. Limpieza del proyecto

Eliminar cache:

```bash
Remove-Item __pycache__ -Recurse -Force
```

---

## 14. Alcance del proyecto

Este agente:

✔ No escanea  
✔ No explota vulnerabilidades  
✔ No ataca sistemas  
✔ Solo procesa datos  

---

# FIN

