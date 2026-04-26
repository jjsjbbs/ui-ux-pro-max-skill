# ClinicBot — Agente WhatsApp para Clínicas

Agente conversacional de IA para cualquier tipo de clínica. Recibe consultas por WhatsApp, califica al paciente, lo geolocaliza y agenda citas automáticamente.

## Flujo del agente

```
Paciente escribe → Bienvenida
    → Detecta tratamiento buscado
        → Pregunta: ¿Qué problema tiene?
        → Pregunta: ¿Desde cuándo?
        → Pregunta: ¿Tratamientos previos?
        → Pregunta: ¿Nivel de urgencia?
            → Evalúa si califica
                ✓ Califica → Pide ubicación → Muestra sucursales cercanas → Ofrece horarios → Confirma cita
                ✗ No califica → Mensaje empático + alternativas
```

## Inicio rápido

### 1. Configurar entorno

```bash
cp .env.example .env
# Editar .env con tus claves
```

### 2. Configurar clínica

```bash
cp config/clinic.example.json config/clinic.json
# Editar clinic.json con los datos de tu clínica
```

### 3. Ejecutar con Docker (recomendado)

```bash
docker-compose up -d
```

### 4. O ejecutar local

```bash
pip install -r requirements.txt
uvicorn agent.main:app --reload --port 8000
```

El dashboard de administración estará disponible en: **http://localhost:8000**

## Conectar con WhatsApp (Twilio)

1. Crea una cuenta en [Twilio](https://twilio.com) y activa el Sandbox de WhatsApp.
2. En el Sandbox, configura el webhook como:
   ```
   https://tu-dominio.com/webhook/whatsapp
   ```
3. Para desarrollo local, usa [ngrok](https://ngrok.com):
   ```bash
   ngrok http 8000
   # Copia la URL https://xxxx.ngrok.io y úsala como webhook
   ```

## Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/webhook/whatsapp` | Webhook Twilio (producción) |
| POST | `/api/chat` | Chat de prueba sin Twilio |
| DELETE | `/api/chat/{phone}` | Reiniciar conversación |
| GET | `/api/sessions` | Listar sesiones activas |
| GET | `/api/sessions/{phone}` | Detalle de sesión |
| GET | `/api/stats` | Estadísticas del agente |
| GET | `/api/clinic` | Información de la clínica |
| GET | `/` | Panel de administración |
| GET | `/health` | Health check |
| GET | `/docs` | Documentación interactiva (Swagger) |

## Configurar tu clínica (`clinic.json`)

El archivo `config/clinic.json` define toda la lógica de tu clínica:

```json
{
  "name": "Mi Clínica",
  "type": "dental",
  "tagline": "Tu sonrisa, nuestra pasión",
  "locations": [...],
  "qualification_rules": {
    "excluded_conditions": ["emergencia cardíaca"]
  }
}
```

Ver `config/clinic.example.json` para un ejemplo completo con 2 sucursales y 8 médicos.

## Personalización

- **Prompts**: Edita `agent/prompts.py` para ajustar el tono y las preguntas.
- **Reglas de cualificación**: Configura en `clinic.json` → `qualification_rules`.
- **Especialidades**: Agrega en cada `location.specialties`.
- **Horarios**: Define por día de semana en `location.schedule`.
- **Idioma**: Cambia `language` en `clinic.json` (soporte multi-idioma próximo).

## Estructura del proyecto

```
clinic-whatsapp-agent/
├── agent/
│   ├── main.py           # FastAPI server + webhooks
│   ├── agent.py          # Motor de IA (Claude) + máquina de estados
│   ├── models.py         # Modelos de datos
│   ├── prompts.py        # Prompts del sistema
│   ├── clinic_config.py  # Configuración y horarios de clínica
│   ├── geolocation.py    # Geolocalización + clínicas cercanas
│   └── session_store.py  # Gestión de sesiones (Redis / memoria)
├── config/
│   ├── clinic.json       # Tu configuración (crear desde .example)
│   └── clinic.example.json
├── dashboard/
│   └── index.html        # Panel de administración
├── tests/
│   └── test_agent.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Ejecutar tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Tecnologías

- **IA**: Claude claude-sonnet-4-6 (Anthropic)
- **API**: FastAPI + Uvicorn
- **WhatsApp**: Twilio Messaging API
- **Sesiones**: Redis (o en memoria)
- **Geolocalización**: OpenStreetMap Nominatim (sin costo, sin API key)
- **Dashboard**: HTML + Tailwind CSS (sin framework JS)
