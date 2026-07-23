
# PDP Control Center Online

Aplicación web conectada al Google Sheets del proyecto.

## Credenciales iniciales
- Usuario: admin
- Contraseña: Mainin2026

Cambie estas credenciales antes de publicar.

## Publicar en Streamlit Community Cloud

1. Cree una cuenta en GitHub.
2. Cree un repositorio llamado `pdp-control-center`.
3. Suba:
   - `app.py`
   - `requirements.txt`
   - `.gitignore`
4. Ingrese a Streamlit Community Cloud.
5. Seleccione `Create app`.
6. Seleccione el repositorio, la rama `main` y el archivo `app.py`.
7. En `Advanced settings > Secrets`, pegue:

[auth]
username = "su_usuario"
password = "su_contraseña_segura"

8. Presione `Deploy`.

## Configurar Google Sheets

El documento debe estar:
Compartir > Acceso general > Cualquier persona con el enlace > Lector.

## Ingreso al sistema

1. Abra el enlace generado por Streamlit.
2. Escriba el usuario y contraseña configurados.
3. Presione INGRESAR.
4. Use los filtros del panel izquierdo.
5. Presione Actualizar datos para volver a leer Google Sheets.
6. Entre a Exportar reporte para descargar el resultado filtrado.

## Seguridad

No suba el archivo `.streamlit/secrets.toml` a GitHub.
Use el panel Secrets de Streamlit para guardar la contraseña.
